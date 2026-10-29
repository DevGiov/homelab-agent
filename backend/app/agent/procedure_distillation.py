"""Proposte di memoria procedurale ricavate dalle esecuzioni dei turni act e plan.

Due esecuzioni insegnano qualcosa di riusabile:
- un errore poi superato (esito "riuscito dopo errori"): una nota sul tool che aveva fallito, per non ripeterlo;
- una modifica riuscita in più passi (almeno due tool, almeno uno che esegue): un piano modello generalizzato.

Una sola chiamata a output vincolato decide se c'è davvero qualcosa da proporre e lo scrive; la proposta resta in
attesa dell'approvazione dell'utente (vedi `app.memory.procedures`).
"""
import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agent import llm_calls
from app.memory import episodes, procedures

logger = logging.getLogger("procedures")


class ProcedureProposal(BaseModel):
    kind: Literal["tool_note", "plan_template", "none"]
    title: str = Field(default="", description="Titolo breve, in italiano")
    content: str = Field(default="", description="La nota o i passi numerati, in italiano")
    tool_name: Optional[str] = Field(default=None, description="Per tool_note: il tool a cui si riferisce la nota")


def worth_distilling(trace: List[Dict[str, Any]]) -> bool:
    from app.security.policy import is_view_tool

    steps = episodes.executed_steps(trace)
    if not steps:
        return False
    outcome = episodes.outcome_of(steps)
    if outcome.startswith("riuscito dopo errori"):
        return True
    return outcome == "riuscito" and len(steps) >= 2 and any(not is_view_tool(s["tool_name"]) for s in steps)


def distill(task: str, trace: List[Dict[str, Any]], thread_id: Optional[str], model: Optional[str] = None) -> Optional[int]:
    """Propone una procedura dall'esecuzione, se ne vale la pena; id della nuova proposta o None."""
    if not worth_distilling(trace):
        return None
    episode = episodes.describe(task, trace)
    tools = sorted({s["tool_name"] for s in episodes.executed_steps(trace)})
    prompt = f"""Execution of a homelab agent turn:
{episode}

Decide whether this execution teaches something reusable for future requests:
- "tool_note": a call failed and a later, different call succeeded. Write the general rule for using that tool that
  avoids the error next time (one or two sentences). tool_name must be one of: {', '.join(tools)}.
- "plan_template": a multi-step change succeeded. Write the reusable numbered procedure, with tool names and
  placeholders such as <vmid> or <hostname> instead of the values specific to this request.
- "none": nothing general to learn (a one-off, an error that was not overcome, a trivial sequence).
Keep stable facts of the homelab (which container runs what) only when the rule depends on them.
Write title and content in Italian."""
    proposal = llm_calls.call_llm_structured(
        prompt,
        "You distill reusable procedures from an agent's tool executions. Propose only what will clearly help again.",
        ProcedureProposal,
        max_tokens=768,
        max_retries=1,
        reasoning_budget=0,
        model=model,
        reasoning_phase=None,
    )
    if proposal is None or proposal.kind == "none":
        return None
    if proposal.kind == "tool_note" and proposal.tool_name not in tools:
        logger.info(f"Nota scartata: tool '{proposal.tool_name}' non usato nell'esecuzione")
        return None
    try:
        procedure_id, created = procedures.propose(
            proposal.kind, proposal.title, proposal.content,
            tool_name=proposal.tool_name if proposal.kind == "tool_note" else None, source="execution", thread_id=thread_id,
        )
    except ValueError as e:
        logger.info(f"Proposta scartata: {e}")
        return None
    return procedure_id if created else None
