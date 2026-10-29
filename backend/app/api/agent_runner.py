"""Esecuzione del grafo LangGraph per le richieste API (sincrona e in streaming)."""
import asyncio
import contextvars
import json
import logging
import queue
import threading
import time
from functools import lru_cache
from typing import List, Optional, Union

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.graph import build_graph
from app.agent.llm_calls import stream_queue, stream_reasoning_phase_count
from app.agent.stream_session import (
    create_session,
    current_session_var,
    get_session,
    remove_session,
)
from app.api.schemas import (
    ChatResponse,
)
from app.llm.providers import (
    get_active_model_name,
)
from app.memory import thread_store
from app.observability.turns import observe_turn

logger = logging.getLogger("api")


@lru_cache(maxsize=1)
def get_app_graph():
    """Grafo compilato condiviso dalle richieste API."""
    return build_graph()


def run_agent_flow(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: Union[str, bool] = "auto", images: Optional[List[str]] = None, security_mode: str = "normal") -> ChatResponse:
    effective_thread_id = thread_id or f"thread_{int(time.time() * 1000)}"
    graph_task = task.strip() if task else ""
    if not graph_task and images:
        graph_task = "Analizza e descrivi l'immagine allegata."

    initial_state = {
        "task": graph_task,
        "images": images,
        "thread_id": effective_thread_id,
        "force_mode": force_mode,
        "reasoning_budget": reasoning_budget,
        "model": model,
        "execute": execute,
        "web_search": web_search,
        "web_prefetch_data": None,
        "web_prefetch_metadata": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
        "incognito": incognito,
        "security_mode": security_mode,
    }

    # Salva immediatamente il messaggio dell'utente nello store SQLite
    title_prompt = task.strip() if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
    needs_title_generation = False
    if not incognito:
        thread_store.save_user_message(effective_thread_id, task, images=images)
        if not thread_store.get_thread_title(effective_thread_id):
            provisional_title = task.strip()[:35] if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
            thread_store.set_thread_title(effective_thread_id, provisional_title)
            needs_title_generation = True

    cfg = {"configurable": {"thread_id": effective_thread_id}}
    sess = create_session(effective_thread_id, task=task, mode=force_mode)
    current_session_var.set(sess)
    try:
        with observe_turn(effective_thread_id, "chat", stopped=sess.is_stopped) as turn:
            final_state = get_app_graph().invoke(initial_state, config=cfg)
            turn.mode = final_state.get("mode")

        mode = final_state.get("mode", force_mode or "plan")
        response_text = final_state.get("final_response", "")
        plan_dict = final_state.get("plan", {})
        tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None

        plan_steps = plan_dict.get("plan_steps") if isinstance(plan_dict, dict) else None
        plan_structure = final_state.get("plan_structure") or (plan_dict.get("plan_structure") if isinstance(plan_dict, dict) else None)
        execution_trace = final_state.get("execution_trace") or (plan_dict.get("execution_log") if isinstance(plan_dict, dict) else None)
        rollback_trace = final_state.get("rollback_trace")
        reasoning_content = final_state.get("reasoning_content")
        web_prefetch = final_state.get("web_prefetch_metadata") or final_state.get("web_prefetch_data")
        metrics = sess.get_metrics()

        t_title = thread_store.get_thread_title(effective_thread_id)
        effective_model_used = model or get_active_model_name()
        resp = ChatResponse(
            thread_id=effective_thread_id,
            mode=mode,
            model=effective_model_used,
            response=response_text,
            tool_used=tool_used,
            plan_steps=plan_steps,
            plan_structure=plan_structure,
            execution_trace=execution_trace,
            rollback_trace=rollback_trace,
            reasoning_content=reasoning_content,
            web_prefetch=web_prefetch,
            metrics=metrics,
            thread_title=t_title,
            approval_required=final_state.get("approval_required"),
            request_id=final_state.get("request_id"),
            approval_prompt=final_state.get("approval_prompt"),
            command_preview=final_state.get("command_preview"),
            command_prefix=final_state.get("command_prefix"),
            risk_reason=final_state.get("risk_reason"),
            security_mode=final_state.get("security_mode", security_mode),
        )

        # Salva la risposta dell'assistente nello store SQLite solo se non in modalità incognito
        if not incognito:
            thread_store.save_assistant_message(effective_thread_id, resp.model_dump())
            if needs_title_generation:
                threading.Thread(
                    target=thread_store.generate_and_save_title,
                    args=(effective_thread_id, title_prompt, model),
                    daemon=True
                ).start()

        return resp
    except Exception as e:
        if not incognito:
            thread_store.save_assistant_message(effective_thread_id, {
                "response": f"[Errore durante l'esecuzione: {str(e)}]",
                "error": True
            })
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}") from e
    finally:
        remove_session(effective_thread_id)



def run_agent_flow_stream(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: Union[str, bool] = "auto", request: Optional[Request] = None, images: Optional[List[str]] = None, security_mode: str = "normal"):
    effective_thread_id = thread_id or f"thread_{int(time.time() * 1000)}"
    graph_task = task.strip() if task else ""
    if not graph_task and images:
        graph_task = "Analizza e descrivi l'immagine allegata."

    initial_state = {
        "task": graph_task,
        "images": images,
        "thread_id": effective_thread_id,
        "force_mode": force_mode,
        "reasoning_budget": reasoning_budget,
        "model": model,
        "execute": execute,
        "web_search": web_search,
        "web_prefetch_data": None,
        "web_prefetch_metadata": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
        "incognito": incognito,
        "security_mode": security_mode,
    }

    # Salva immediatamente il messaggio dell'utente nello store SQLite
    title_prompt = task.strip() if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
    needs_title_generation = False
    if not incognito:
        thread_store.save_user_message(effective_thread_id, task, images=images)
        if not thread_store.get_thread_title(effective_thread_id):
            provisional_title = task.strip()[:35] if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
            thread_store.set_thread_title(effective_thread_id, provisional_title)
            needs_title_generation = True

    # Se c'è già una sessione attiva per questo thread, ci colleghiamo ad essa
    existing_sess = get_session(effective_thread_id)
    if existing_sess and existing_sess.is_active():
        sess = existing_sess
    else:
        sess = create_session(effective_thread_id, task=graph_task, mode=force_mode)
        cfg = {"configurable": {"thread_id": effective_thread_id}}

        def worker():
            stream_queue.set(sess)
            stream_reasoning_phase_count.set(0)
            current_session_var.set(sess)
            try:
                with observe_turn(effective_thread_id, "chat", stopped=sess.is_stopped) as turn:
                    final_state = get_app_graph().invoke(initial_state, config=cfg)
                    turn.mode = final_state.get("mode")
                mode = final_state.get("mode", force_mode or "plan")
                response_text = final_state.get("final_response", "")
                plan_dict = final_state.get("plan", {})
                tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None
                plan_steps = plan_dict.get("plan_steps") if isinstance(plan_dict, dict) else None
                plan_structure = final_state.get("plan_structure") or (plan_dict.get("plan_structure") if isinstance(plan_dict, dict) else None)
                execution_trace = final_state.get("execution_trace") or (plan_dict.get("execution_log") if isinstance(plan_dict, dict) else None)
                rollback_trace = final_state.get("rollback_trace")
                reasoning_content = final_state.get("reasoning_content")
                web_prefetch = final_state.get("web_prefetch_metadata") or final_state.get("web_prefetch_data")
                metrics = sess.get_metrics()

                t_title = thread_store.get_thread_title(effective_thread_id)
                effective_model_used = model or get_active_model_name()
                resp = ChatResponse(
                    thread_id=effective_thread_id,
                    mode=mode,
                    model=effective_model_used,
                    response=response_text,
                    tool_used=tool_used,
                    plan_steps=plan_steps,
                    plan_structure=plan_structure,
                    execution_trace=execution_trace,
                    rollback_trace=rollback_trace,
                    reasoning_content=reasoning_content,
                    web_prefetch=web_prefetch,
                    metrics=metrics,
                    thread_title=t_title,
                    approval_required=final_state.get("approval_required"),
                    request_id=final_state.get("request_id"),
                    approval_prompt=final_state.get("approval_prompt"),
                    command_preview=final_state.get("command_preview"),
                    command_prefix=final_state.get("command_prefix"),
                    risk_reason=final_state.get("risk_reason"),
                    security_mode=final_state.get("security_mode", security_mode),
                )
                if not incognito and not sess.is_stopped():
                    thread_store.save_assistant_message(effective_thread_id, resp.model_dump())
                    if needs_title_generation:
                        threading.Thread(
                            target=thread_store.generate_and_save_title,
                            args=(effective_thread_id, title_prompt, model),
                            daemon=True
                        ).start()
                sess.put({"type": "final", "response": resp.model_dump()})
            except Exception as e:
                if not incognito and not sess.is_stopped():
                    thread_store.save_assistant_message(effective_thread_id, {
                        "response": f"[Errore durante l'elaborazione: {str(e)}]",
                        "error": True
                    })
                sess.put({"type": "error", "error": str(e)})
            finally:
                if not incognito and not sess.is_stopped():
                    msgs = thread_store.get_thread_messages(effective_thread_id)
                    has_assistant = any(m.get("sender") == "assistant" for m in msgs)
                    if not has_assistant:
                        thread_store.save_assistant_message(effective_thread_id, {
                            "response": "[Esecuzione completata]",
                            "error": False
                        })
                        if needs_title_generation:
                            threading.Thread(
                                target=thread_store.generate_and_save_title,
                                args=(effective_thread_id, title_prompt, model),
                                daemon=True
                            ).start()
                sess.put(None)

        ctx = contextvars.copy_context()
        t = threading.Thread(target=ctx.run, args=(worker,))
        t.start()

    async def event_generator():
        sub_q = sess.subscribe()
        try:
            # Se la sessione ha già prodotto reasoning o token, invia uno snapshot di sync iniziale
            if sess.reasoning_content or sess.partial_content or sess.is_paused():
                yield f"data: {json.dumps(sess.get_snapshot(), ensure_ascii=False)}\n\n"

            while True:
                if request is not None and await request.is_disconnected():
                    logger.info(f"Client SSE disconnesso per thread '{effective_thread_id}'. L'elaborazione continua in background.")
                    break
                if not sess.is_active() and sub_q.empty():
                    break
                try:
                    item = await asyncio.to_thread(sub_q.get, timeout=0.25)
                except queue.Empty:
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            sess.unsubscribe(sub_q)
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
