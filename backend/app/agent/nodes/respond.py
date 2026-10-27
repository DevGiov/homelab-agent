import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, List, Optional

from app.agent import llm_calls
from app.agent.monitoring import AgentSpan, log_span
from app.agent.state import AgentState
from app.core.config import settings
from app.memory import letta_client, transcript

logger = logging.getLogger("graph")


def _format_tool_result(tool_name: str, result: Any) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"❌ **Errore nell'esecuzione del tool `{tool_name}`**:\n```\n{result['error']}\n```"

    raw_data = result
    if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
        text_parts = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        if text_parts:
            raw_text = "\n".join(text_parts)
            try:
                raw_data = json.loads(raw_text)
            except Exception:
                raw_data = raw_text

    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            pass

    if "list_containers" in str(tool_name) and isinstance(raw_data, list):
        lines = [
            f"**Esito elaborazione tool**: `{tool_name}`\n",
            "Ecco l'elenco dei container LXC rilevati sul server Proxmox:\n",
            "| VMID | Nome | Stato | CPU (Cores) | RAM Allocata | Tipo |",
            "| :--- | :--- | :---: | :---: | :---: | :---: |"
        ]
        for c in sorted(raw_data, key=lambda x: int(x.get("vmid", 0)) if str(x.get("vmid", "0")).isdigit() else 0):
            vmid = c.get("vmid", "N/A")
            name = c.get("name", "Unnamed")
            status = str(c.get("status", "")).lower()
            status_icon = "🟢 `running`" if status == "running" else ("🔴 `stopped`" if status == "stopped" else f"`{status}`")
            cpus = c.get("cpus", "-")
            maxmem = c.get("maxmem", 0)
            mem_mb = int(maxmem / (1024 * 1024)) if isinstance(maxmem, (int, float)) and maxmem > 0 else "-"
            c_type = c.get("type", "lxc")
            lines.append(f"| **{vmid}** | {name} | {status_icon} | {cpus} | {mem_mb} MB | {c_type} |")
        return "\n".join(lines)

    if "list_templates" in str(tool_name) and isinstance(raw_data, list):
        lines = [
            f"**Esito elaborazione tool**: `{tool_name}`\n",
            "Ecco i template di servizio disponibili:\n"
        ]
        for t in raw_data:
            if isinstance(t, dict):
                key = t.get("key", "")
                desc = t.get("description", "")
                vmid = t.get("source_vmid", "")
                tags = ", ".join(t.get("tags", [])) if isinstance(t.get("tags"), list) else str(t.get("tags", ""))
                lines.append(f"- **{key}** (VMID `{vmid}`): {desc} *(Tags: {tags})*")
            else:
                lines.append(f"- {t}")
        return "\n".join(lines)

    if isinstance(raw_data, (dict, list)):
        pretty = json.dumps(raw_data, indent=2, ensure_ascii=False)
        return f"**Esito elaborazione tool**: `{tool_name}`\n\n```json\n{pretty}\n```"

    return f"**Esito elaborazione tool**: `{tool_name}`\n\n{raw_data}"


def extract_salient_facts(task: str, response: str, memory_context: str, model: Optional[str] = None) -> List[str]:
    """
    Estrae fatti salienti dalla conversazione per il salvataggio in memoria archivistica.
    """
    if not task or not response:
        return []

    prompt = f"""Language Directive: Extract facts preserving proper entities and user intent.
Extract salient facts from the following conversation that may be valuable for long-term memory.
Include:
- User preferences (e.g. "prefers Debian-based LXC containers")
- Decisions made (e.g. "created web service to test performance")
- Infrastructure context (e.g. "static IP allocated 192.168.1.180")

User task: {task}
Assistant response: {response}
Existing context: {memory_context}

Salient facts (list maximum 5 concise bullet points, one per line):"""

    raw_res = llm_calls.call_llm(prompt, system_prompt="You are an expert assistant for extracting salient facts and entities.", max_tokens=512, temperature=0.3, reasoning_budget=0, model=model, stream_mode="none")
    raw = raw_res.get("content", "") if isinstance(raw_res, dict) else ""
    if not raw:
        return []

    lines = [line.strip("- *").strip() for line in raw.split("\n") if line.strip()]
    return [line for line in lines if len(line) > 5][:5]


def respond_node(state: AgentState) -> AgentState:
    """Formats final response if not already set, appends assistant message to file system memory, logs monitoring span, and extracts salient facts."""
    thread_id = state.get("thread_id") or "default_thread"
    task = state.get("task", "")
    agent_id = state.get("agent_id")
    memory_context = state.get("memory_context") or ""

    formatted = state.get("final_response")
    if not formatted:
        plan = state.get("plan", {})
        mode = state.get("mode", "chat")

        if plan.get("tool_needed"):
            tool_name = plan.get("tool_name")
            result = state.get("tool_result")
            formatted_result = _format_tool_result(str(tool_name), result)
            formatted = f"[Mode: {mode.upper()}]\n{formatted_result}"
        else:
            direct_ans = plan.get("direct_answer", "")
            formatted = f"[Mode: {mode.upper()}]\n{direct_ans}"

    incognito = state.get("incognito", False)

    if thread_id and formatted and not incognito:
        transcript.append_message(thread_id, "assistant", formatted)

    # 1. Logging dello span di monitoraggio (Task 4.2)
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    span = AgentSpan(
        session_id=session_id,
        thread_id=thread_id,
        task=task,
        end_time=datetime.now(UTC),
        llm_latency_ms=state.get("llm_latency_ms", 120.0),
        prompt_tokens=state.get("prompt_tokens", len(task.split()) + 50),
        completion_tokens=state.get("completion_tokens", len(formatted.split())),
        retrieval_hit_rate=1.0
    )
    log_span(span)

    # 2. Estrazione fatti salienti e salvataggio in Archival Memory (Task 4.3) - Skipped in incognito mode
    if not incognito:
        try:
            facts = extract_salient_facts(task, formatted, memory_context, model=state.get("model"))
            if facts:
                logger.info(f"Fatti salienti estratti ({len(facts)}): {facts}")
                if agent_id:
                    for fact in facts:
                        letta_client.save_archival_memory(agent_id, fact)
                os.makedirs(settings.memory_dir, exist_ok=True)
                facts_file = os.path.join(settings.memory_dir, f"salient_facts_{thread_id}.txt")
                with open(facts_file, "a", encoding="utf-8") as f:
                    for fact in facts:
                        f.write(f"- {fact}\n")
                # --- Fase 2.1: indicizza i fatti nel vector store per recall semantico cross-thread ---
                try:
                    from app.memory.vector_store import add_memory
                    for fact in facts:
                        add_memory(fact, kind="fact", thread_id=thread_id, metadata={"source": "salient_facts"})
                except Exception as ve:
                    logger.warning(f"Indicizzazione vector store fallita (non bloccante): {ve}")
        except Exception as e:
            logger.warning(f"Errore durante l'estrazione o il salvataggio dei fatti salienti: {e}")
    else:
        logger.info(f"Modalità Incognito attiva per thread '{thread_id}': estrazione fatti e salvataggio memoria saltati.")

    return {
        "final_response": formatted,
        "web_prefetch_data": state.get("web_prefetch_data"),
        "web_prefetch_metadata": state.get("web_prefetch_metadata"),
        "approval_required": state.get("approval_required"),
        "request_id": state.get("request_id"),
        "approval_prompt": state.get("approval_prompt"),
        "command_preview": state.get("command_preview"),
        "command_prefix": state.get("command_prefix"),
        "risk_reason": state.get("risk_reason"),
        "security_mode": state.get("security_mode") or "normal",
    }
