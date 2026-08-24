import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("letta_client")

LETTA_URL = config.LETTA_URL.rstrip('/')
LETTA_API_KEY = config.LETTA_API_KEY

HEADERS = {
    "Authorization": f"Bearer {LETTA_API_KEY}",
    "Content-Type": "application/json"
} if LETTA_API_KEY else {"Content-Type": "application/json"}

DEFAULT_TIMEOUT = 5.0

def _get_llm_config(client: httpx.Client):
    """Retrieves default llm_config from existing agent if available."""
    try:
        r = client.get(f"{LETTA_URL}/v1/agents/", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            agents = r.json()
            if agents and isinstance(agents, list) and "llm_config" in agents[0]:
                return agents[0]["llm_config"]
    except Exception:
        pass
    return None

def create_thread(name: str, memory_blocks: list = None) -> str:
    """
    Creates or retrieves a Letta agent/thread by name.
    Returns agent_id (str) or None if request fails.
    """
    if not LETTA_URL or not LETTA_API_KEY:
        logger.warning("LETTA_URL or LETTA_API_KEY missing")
        return None

    with httpx.Client(follow_redirects=True) as client:
        # 1. Search existing agent by name
        for attempt in range(2):
            try:
                r = client.get(f"{LETTA_URL}/v1/agents/", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
                if r.status_code == 200:
                    agents = r.json()
                    if isinstance(agents, list):
                        for ag in agents:
                            if ag.get("name") == name:
                                return ag.get("id")
                break
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} listing Letta agents failed: {e}")

        # 2. If not found, create new agent
        llm_config = _get_llm_config(client)
        payload = {"name": name}
        if llm_config:
            payload["llm_config"] = llm_config
        if memory_blocks:
            payload["memory_blocks"] = memory_blocks

        for attempt in range(2):
            try:
                r = client.post(f"{LETTA_URL}/v1/agents/", headers=HEADERS, json=payload, timeout=DEFAULT_TIMEOUT)
                if r.status_code in [200, 201]:
                    data = r.json()
                    return data.get("id")
                else:
                    logger.warning(f"Letta create_thread status {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} creating Letta thread failed: {e}")

    return None

def save_memory(agent_id: str, content: str) -> bool:
    """
    Saves a conversation turn into Letta's archival memory.
    This is an instant vector/passage insertion that DOES NOT trigger
    an agent LLM inference turn on the Letta server.
    """
    if not agent_id or not LETTA_URL:
        return False

    payload = {"text": content}
    try:
        with httpx.Client(follow_redirects=True) as client:
            r = client.post(f"{LETTA_URL}/v1/agents/{agent_id}/archival-memory", headers=HEADERS, json=payload, timeout=DEFAULT_TIMEOUT)
            if r.status_code in [200, 201]:
                logger.info(f"Successfully saved archival memory turn for agent {agent_id}")
                return True
            else:
                logger.warning(f"Letta save_memory status {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"save_memory failed: {e}")
    return False

def save_archival_memory(agent_id: str, key: str, value: str) -> bool:
    """Saves a key-value pair into Letta's archival memory."""
    if not agent_id or not key or not value:
        return False
    content = f"[{key}] {value}"
    return save_memory(agent_id, content)

def get_archival_memory(agent_id: str, key: str) -> Optional[str]:
    """Retrieves a key-value pair from Letta's archival memory passages."""
    if not agent_id or not key:
        return None
    passages = get_messages(agent_id, limit=100)
    tag = f"[{key}]"
    for item in passages:
        if isinstance(item, dict):
            txt = item.get("text") or item.get("content") or ""
            if tag in txt:
                return txt.replace(tag, "").strip()
    return None

def send_message(agent_id: str, role: str, content: str) -> dict:
    """
    Saves message memory to Letta using fast archival insertion.
    """
    success = save_memory(agent_id, content)
    return {"status": "ok"} if success else None

def get_messages(agent_id: str, limit: int = 50) -> list:
    """
    Retrieves memory passages from Letta archival memory (or message log).
    """
    if not agent_id or not LETTA_URL:
        return []

    with httpx.Client(follow_redirects=True) as client:
        # Try archival memory passages first
        try:
            r = client.get(f"{LETTA_URL}/v1/agents/{agent_id}/archival-memory?limit={limit}", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                passages = r.json()
                if passages and isinstance(passages, list):
                    return passages
        except Exception as e:
            logger.warning(f"get_messages archival fetch failed: {e}")

        # Fallback to message history
        try:
            r = client.get(f"{LETTA_URL}/v1/agents/{agent_id}/messages?limit={limit}", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.warning(f"get_messages fallback failed: {e}")

    return []

def filter_clean_messages(messages: list) -> list:
    """
    Filters raw Letta messages or archival passages to return clean user and main-agent turns.
    """
    if not messages or not isinstance(messages, list):
        return []

    clean_msgs = []
    for item in messages:
        if not isinstance(item, dict):
            continue

        txt = item.get("text") or item.get("content") or item.get("message") or ""
        if not txt:
            continue

        msg_id = item.get("id") or "msg"
        date_val = item.get("created_at") or item.get("date")

        m_type = str(item.get("message_type") or item.get("role") or "").lower()
        if "system" in m_type or "reasoning" in m_type or "tool" in m_type:
            continue
        if m_type in ["assistant_message", "assistant"] and "User: " not in txt:
            continue

        if "User: " in txt and "Assistant: " in txt:
            parts = txt.split("Assistant: ", 1)
            user_part = parts[0].replace("User: ", "").strip()
            ast_part = parts[1].strip() if len(parts) > 1 else ""

            if user_part:
                clean_msgs.append({
                    "id": f"{msg_id}_u",
                    "date": date_val,
                    "message_type": "user_message",
                    "content": user_part
                })
            if ast_part:
                clean_msgs.append({
                    "id": f"{msg_id}_a",
                    "date": date_val,
                    "message_type": "assistant_message",
                    "content": ast_part
                })
        else:
            role = "user_message" if "user" in m_type or not m_type else "assistant_message"
            clean_msgs.append({
                "id": msg_id,
                "date": date_val,
                "message_type": role,
                "content": txt
            })

    return clean_msgs


def delete_thread(agent_id: str) -> bool:
    """Deletes a Letta agent/thread by agent_id."""
    if not agent_id or not LETTA_URL:
        return False
    try:
        with httpx.Client(follow_redirects=True) as client:
            r = client.delete(f"{LETTA_URL}/v1/agents/{agent_id}", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            return r.status_code in [200, 204]
    except Exception as e:
        logger.warning(f"Failed to delete Letta thread {agent_id}: {e}")
        return False


def list_agents() -> list:
    """Lists all Letta agents."""
    if not LETTA_URL:
        return []
    try:
        with httpx.Client(follow_redirects=True) as client:
            r = client.get(f"{LETTA_URL}/v1/agents/", headers=HEADERS, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"Failed to list Letta agents: {e}")
    return []


def delete_all_threads() -> int:
    """Deletes all Letta agents/threads. Returns count of deleted agents."""
    agents = list_agents()
    deleted = 0
    for ag in agents:
        aid = ag.get("id")
        if aid and delete_thread(aid):
            deleted += 1
    return deleted


import math
from collections import defaultdict


class BM25Retriever:
    """BM25 sparse retriever for text search over archival documents."""
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freq: Dict[str, int] = defaultdict(int)
        self.doc_lengths: List[int] = []
        self.avg_doc_length: float = 0.0
        self.docs: List[str] = []

    def index(self, docs: List[str]):
        self.docs = docs
        if not docs:
            self.doc_lengths = []
            self.avg_doc_length = 0.0
            self.doc_freq.clear()
            return
        self.doc_lengths = [len(doc.split()) for doc in docs]
        self.avg_doc_length = sum(self.doc_lengths) / len(docs)
        self.doc_freq.clear()
        for doc in docs:
            terms = set(re.findall(r'\w+', doc.lower()))
            for term in terms:
                self.doc_freq[term] += 1

    def search(self, query: str, k: int = 50) -> List[Tuple[int, float]]:
        if not self.docs:
            return []
        query_terms = re.findall(r'\w+', query.lower())
        scores = defaultdict(float)
        num_docs = len(self.docs)

        for doc_idx, doc in enumerate(self.docs):
            doc_terms = re.findall(r'\w+', doc.lower())
            doc_len = self.doc_lengths[doc_idx]
            score = 0.0

            for term in query_terms:
                if term in self.doc_freq:
                    tf = doc_terms.count(term)
                    df = self.doc_freq[term]
                    idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
                    denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_length or 1.0)))
                    term_score = idf * ((tf * (self.k1 + 1.0)) / (denom or 1.0))
                    score += term_score

            scores[doc_idx] = score

        top_k = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return top_k


def reciprocal_rank_fusion(rank_lists: List[List[Tuple[int, float]]], k: int = 60, top_n: int = 50) -> List[Tuple[int, float]]:
    """
    Combines multiple ranked lists using Reciprocal Rank Fusion (RRF).
    """
    rrf_scores = defaultdict(float)

    for rank_list in rank_lists:
        for rank, (doc_idx, _) in enumerate(rank_list, start=1):
            rrf_scores[doc_idx] += 1.0 / (k + rank)

    top_n_fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return top_n_fused


def search_archival_memory_hybrid(agent_id: str, query: str, k: int = 50, use_hybrid: bool = True) -> List[Dict[str, Any]]:
    """
    Hybrid retrieval (BM25 + Dense + RRF) for Letta archival memory.
    """
    dense_docs = get_archival_memory(agent_id, limit=k*2)
    if not dense_docs:
        return []

    if not use_hybrid:
        return dense_docs[:k]

    doc_texts = [doc.get("text") or doc.get("content") or str(doc) for doc in dense_docs]

    bm25 = BM25Retriever()
    bm25.index(doc_texts)
    bm25_results = bm25.search(query, k=k*2)

    dense_results = [(i, float(doc.get("score", 1.0 / (i + 1)))) for i, doc in enumerate(dense_docs)]

    fused_indices = reciprocal_rank_fusion([bm25_results, dense_results], k=60, top_n=k)

    hybrid_docs = [dense_docs[idx] for idx, _ in fused_indices]
    logger.info(f"Hybrid retrieval: {len(hybrid_docs)} documenti costituiti via BM25 + Dense + RRF")
    return hybrid_docs


