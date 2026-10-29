import json
import logging
from typing import Any

from app.agent.fact_extraction import remember_turn
from app.agent.state import AgentState
from app.memory.episodes import remember_episode

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


def respond_node(state: AgentState) -> AgentState:
    """Formats final response if not already set and saves the facts worth remembering and, for act/plan turns that ran
    tools, the execution episode (the message itself is saved by the caller in thread_store)."""
    thread_id = state.get("thread_id") or "default_thread"
    task = state.get("task", "")
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

    # Fatti da ricordare, con le entità che citano (non in incognito)
    if not incognito:
        try:
            created = remember_turn(task, formatted, memory_context, thread_id, model=state.get("model"))
            if created:
                logger.info(f"Memoria: {created} fatti nuovi dal thread '{thread_id}'")
        except Exception as e:
            logger.warning(f"Estrazione dei fatti non riuscita (non bloccante): {e}")
        if state.get("mode") in ("act", "plan") and state.get("execution_trace"):
            try:
                if remember_episode(task, state["mode"], state["execution_trace"], thread_id):
                    logger.info(f"Memoria: episodio di esecuzione salvato dal thread '{thread_id}'")
            except Exception as e:
                logger.warning(f"Salvataggio dell'episodio non riuscito (non bloccante): {e}")
    else:
        logger.info(f"Modalità Incognito attiva per thread '{thread_id}': estrazione fatti saltata.")

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
