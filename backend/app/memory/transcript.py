"""Trascrizione JSONL append-only dei thread: audit, disaster recovery e fallback quando Letta non risponde."""
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, List

from app.core.config import settings

logger = logging.getLogger("graph")


def append_message(thread_id: str, role: str, content: str):
    """Scrivi un messaggio su file JSONL (append-only) per audit e disaster recovery."""
    if not thread_id or not content:
        return
    try:
        os.makedirs(settings.memory_dir, exist_ok=True)
        filepath = os.path.join(settings.memory_dir, f"{thread_id}.jsonl")
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "role": role,
            "content": content
        }
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"Messaggio ({role}) salvato su file di memoria: {filepath}")
    except Exception as e:
        logger.warning(f"Errore scrittura memoria file system {thread_id}: {e}")

def read_messages(thread_id: str) -> List[Dict[str, Any]]:
    """Legge i messaggi storici dal file JSONL locale in caso di assenza o fallback di Letta."""
    if not thread_id:
        return []
    filepath = os.path.join(settings.memory_dir, f"{thread_id}.jsonl")
    if not os.path.exists(filepath):
        return []
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        role_type = "user_message" if data.get("role") == "user" else "assistant_message"
                        messages.append({
                            "message_type": role_type,
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp")
                        })
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Errore lettura file memoria {filepath}: {e}")
    return messages
