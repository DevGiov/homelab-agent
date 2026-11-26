"""Esecuzione del grafo LangGraph per le richieste API (sincrona e in streaming)."""
import asyncio
import contextvars
import json
import logging
import queue
import threading
import time
from functools import lru_cache
from typing import List, Optional, Tuple, Union

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent import turn_checkpoints
from app.agent.graph import build_graph
from app.agent.llm_calls import channel_style_var, stream_queue, stream_reasoning_phase_count
from app.agent.nodes.respond import respond_node
from app.agent.stream_session import (
    StreamSession,
    create_session,
    current_session_var,
    get_session,
    remove_session,
)
from app.agent.turn_resume import meta_of, resume_checkpoint
from app.api.schemas import (
    ChatResponse,
)
from app.llm import providers
from app.memory import thread_store
from app.observability.turns import observe_turn
from app.security import detectors, flows
from app.security.flows import Tag

logger = logging.getLogger("api")


@lru_cache(maxsize=1)
def get_app_graph():
    """Grafo compilato condiviso dalle richieste API."""
    return build_graph()


def turn_selection(thread_id: Optional[str], provider: Optional[str], model: Optional[str]) -> Tuple[str, Optional[str]]:
    """Provider e modello di un turno (docs/providers/PROVIDERS_DESIGN.md, 5.8.6). Senza né provider né modello, una
    conversazione esistente continua con la coppia salvata con lei (anche un canale che prosegue un thread); altrimenti,
    o senza coppia salvata, vale il provider predefinito."""
    if not provider and not model:
        provider, model = thread_store.saved_thread_model(thread_id)
    return provider or providers.default_provider_name(), model


def _turn_model(provider: str, model: Optional[str]) -> Optional[str]:
    """Il modello da mostrare per il turno: quello scelto, altrimenti il predefinito del provider del turno."""
    if model:
        return model
    try:
        return providers.default_model_name(provider)
    except providers.ProviderUnavailableError:
        return None


def _chat_response(final_state: dict, thread_id: str, force_mode: Optional[str], provider: str, model: Optional[str],
                   security_mode: str, sess) -> ChatResponse:
    plan_dict = final_state.get("plan", {})
    plan_dict = plan_dict if isinstance(plan_dict, dict) else {}
    return ChatResponse(
        thread_id=thread_id,
        mode=final_state.get("mode", force_mode or "plan"),
        provider=provider,
        model=_turn_model(provider, model),
        response=final_state.get("final_response", ""),
        tool_used=plan_dict.get("tool_name"),
        plan_steps=plan_dict.get("plan_steps"),
        plan_structure=final_state.get("plan_structure") or plan_dict.get("plan_structure"),
        execution_trace=final_state.get("execution_trace") or plan_dict.get("execution_log"),
        rollback_trace=final_state.get("rollback_trace"),
        reasoning_content=final_state.get("reasoning_content"),
        web_prefetch=final_state.get("web_prefetch_metadata") or final_state.get("web_prefetch_data"),
        metrics=sess.get_metrics(),
        thread_title=thread_store.get_thread_title(thread_id),
        approval_required=final_state.get("approval_required"),
        request_id=final_state.get("request_id"),
        approval_prompt=final_state.get("approval_prompt"),
        command_preview=final_state.get("command_preview"),
        command_prefix=final_state.get("command_prefix"),
        risk_reason=final_state.get("risk_reason"),
        expires_at=final_state.get("expires_at"),
        security_mode=final_state.get("security_mode", security_mode),
        sensitivity=flows.join(final_state.get("tag")).to_dict(),
    )


def _input_tag(thread_id: str, task: str, images: Optional[List[str]], sensitivity: Optional[str], incognito: bool) -> Tag:
    """Tag del messaggio dell'utente: il livello della conversazione (salvato con il thread se l'utente lo sceglie
    ora), alzato dai rilevatori; le immagini allegate possono contenere testo scritto da altri.

    Un segreto che l'utente scrive lui stesso resta `private` (lo vede il modello locale, non esce): `secret` è per i
    segreti che il codice tiene fuori da ogni prompt."""
    if sensitivity and not incognito:
        previous = thread_store.get_thread_sensitivity(thread_id)
        if previous != sensitivity:
            thread_store.set_thread_sensitivity(thread_id, sensitivity)
            logger.info(f"Livello del thread '{thread_id}': {previous or 'public'} -> {sensitivity}")
    level = sensitivity or thread_store.get_thread_sensitivity(thread_id) or "public"
    floor = flows.tag_of(level, f"conversazione:{level}") if level != "public" else flows.PUBLIC_TAG
    try:
        from app.memory import facts
        persons = [e["name"] for e in facts.list_entities(entity_type="person") if e.get("name")]
    except Exception:
        persons = []
    found = detectors.tag_for(task or "", "messaggio", persons)
    if found.label == flows.Label.SECRET:
        found = flows.Tag(flows.Label.PRIVATE, found.untrusted, found.reasons)
    image_tag = flows.tag_of(flows.Label.PUBLIC, "immagine", untrusted=True) if images else None
    return flows.join(floor, found, image_tag)


def thread_has_active_turn(thread_id: Optional[str]) -> bool:
    sess = get_session(thread_id) if thread_id else None
    return bool(sess and sess.is_active())


def start_turn_resume(checkpoint: dict, request_id: str, approved: bool) -> str:
    """Riprende in background il turno sospeso su `request_id`, nella sessione di streaming del suo thread (la UI ci si
    aggancia con /v1/threads/{id}/stream), e salva la risposta come per un turno normale. Restituisce il thread."""
    meta = meta_of(checkpoint)
    thread_id, mode, model = meta["thread_id"], meta.get("mode"), meta.get("model")
    # Un turno salvato prima dei provider per richiesta non ha il suo: vale il predefinito
    provider = meta.get("provider") or providers.default_provider_name()
    incognito, security_mode = meta.get("incognito", False), meta.get("security_mode", "normal")
    turn_checkpoints.delete(request_id)
    sess = create_session(thread_id, task=meta.get("task", ""), mode=mode)

    def worker():
        stream_queue.set(sess)
        stream_reasoning_phase_count.set(0)
        current_session_var.set(sess)
        providers.turn_provider_var.set(provider)
        try:
            with observe_turn(thread_id, "chat", stopped=sess.is_stopped) as turn:
                turn.mode = mode
                result = resume_checkpoint(checkpoint, request_id, approved)
                state = {"task": meta.get("task", ""), "thread_id": thread_id, "mode": mode, "provider": provider,
                         "model": model, "incognito": incognito, "security_mode": security_mode, **result}
                state.update(respond_node(state))
            resp = _chat_response(state, thread_id, mode, provider, model, security_mode, sess)
            if not incognito and not sess.is_stopped():
                thread_store.save_assistant_message(thread_id, resp.model_dump())
            sess.put({"type": "final", "response": resp.model_dump()})
        except Exception as e:
            logger.error(f"Ripresa del turno dopo l'approvazione '{request_id}' non riuscita: {e}", exc_info=True)
            if not incognito and not sess.is_stopped():
                thread_store.save_assistant_message(thread_id, {"response": f"[Errore durante la ripresa: {str(e)}]", "error": True})
            sess.put({"type": "error", "error": str(e)})
        finally:
            sess.put(None)

    threading.Thread(target=contextvars.copy_context().run, args=(worker,), daemon=True).start()
    return thread_id


def run_agent_flow(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: Union[str, bool] = "auto", images: Optional[List[str]] = None, security_mode: str = "normal", sensitivity: Optional[str] = None, provider: Optional[str] = None) -> ChatResponse:
    """Turno sincrono. `provider`: quello della richiesta (turn_selection); vale per tutte le chiamate del turno."""
    provider, model = turn_selection(thread_id, provider, model)
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
        "provider": provider,
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
    input_tag = _input_tag(effective_thread_id, graph_task, images, sensitivity, incognito)
    initial_state["tag"] = input_tag.to_dict()

    # Salva immediatamente il messaggio dell'utente nello store SQLite
    title_prompt = task.strip() if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
    needs_title_generation = False
    if not incognito:
        thread_store.save_user_message(effective_thread_id, task, images=images, sensitivity=input_tag.label.key)
        thread_store.set_thread_model(effective_thread_id, provider, model)
        if not thread_store.get_thread_title(effective_thread_id):
            provisional_title = task.strip()[:35] if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
            thread_store.set_thread_title(effective_thread_id, provisional_title)
            needs_title_generation = True

    cfg = {"configurable": {"thread_id": effective_thread_id}}
    sess = create_session(effective_thread_id, task=task, mode=force_mode)
    current_session_var.set(sess)
    provider_token = providers.turn_provider_var.set(provider)
    try:
        with observe_turn(effective_thread_id, "chat", stopped=sess.is_stopped) as turn:
            final_state = get_app_graph().invoke(initial_state, config=cfg)
            turn.mode = final_state.get("mode")

        resp = _chat_response(final_state, effective_thread_id, force_mode, provider, model, security_mode, sess)

        # Salva la risposta dell'assistente nello store SQLite solo se non in modalità incognito
        if not incognito:
            thread_store.save_assistant_message(effective_thread_id, resp.model_dump())
            if needs_title_generation:
                threading.Thread(
                    target=thread_store.generate_and_save_title,
                    args=(effective_thread_id, title_prompt, model, input_tag, provider),
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
        providers.turn_provider_var.reset(provider_token)
        remove_session(effective_thread_id)



def start_turn(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: Union[str, bool] = "auto", images: Optional[List[str]] = None, security_mode: str = "normal", sensitivity: Optional[str] = None, *, channel: Optional[str] = None, extra_tag: Optional[Tag] = None, style_hint: Optional[str] = None, provider: Optional[str] = None) -> StreamSession:
    """Avvia un turno senza il trasporto HTTP: salva il messaggio dell'utente, crea la `StreamSession` del thread e
    fa partire il grafo in un thread di lavoro. Restituisce la sessione (il thread è `sess.thread_id`): la Web UI vi si
    iscrive con SSE (`run_agent_flow_stream`), un canale con `sess.subscribe()`.

    Se il thread ha già un turno attivo non ne parte un altro: il messaggio è salvato e si restituisce quello in corso.

    `channel`: id del canale da cui arriva il messaggio (finisce nello stato del grafo). La modalità di sicurezza di un
    turno da canale è sempre `normal`: un account di messaggistica compromesso non deve poter chiedere `dangerous`.
    `extra_tag`: etichetta aggiunta a quella della richiesta, per contenuto scritto da altri (un messaggio inoltrato:
    pubblico e non attendibile). `style_hint`: una riga di stile che le risposte del modello ricevono (capacità del canale).
    `provider`: il provider della richiesta (turn_selection). Il lavoratore lo imposta come provider del turno:
    ogni chiamata interna del turno lo usa, anche quando un altro turno in parallelo ne usa un altro."""
    provider, model = turn_selection(thread_id, provider, model)
    if channel:
        security_mode = "normal"
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
        "provider": provider,
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
    if channel:
        initial_state["channel"] = channel
    input_tag = flows.join(_input_tag(effective_thread_id, graph_task, images, sensitivity, incognito), extra_tag)
    initial_state["tag"] = input_tag.to_dict()

    # Salva immediatamente il messaggio dell'utente nello store SQLite
    title_prompt = task.strip() if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
    needs_title_generation = False
    if not incognito:
        thread_store.save_user_message(effective_thread_id, task, images=images, sensitivity=input_tag.label.key)
        thread_store.set_thread_model(effective_thread_id, provider, model)
        if not thread_store.get_thread_title(effective_thread_id):
            provisional_title = task.strip()[:35] if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
            thread_store.set_thread_title(effective_thread_id, provisional_title)
            needs_title_generation = True

    # Se c'è già una sessione attiva per questo thread, ci colleghiamo ad essa
    existing_sess = get_session(effective_thread_id)
    if existing_sess and existing_sess.is_active():
        return existing_sess

    sess = create_session(effective_thread_id, task=graph_task, mode=force_mode)
    cfg = {"configurable": {"thread_id": effective_thread_id}}

    def worker():
        stream_queue.set(sess)
        stream_reasoning_phase_count.set(0)
        current_session_var.set(sess)
        channel_style_var.set(style_hint or None)
        providers.turn_provider_var.set(provider)
        try:
            with observe_turn(effective_thread_id, "chat", stopped=sess.is_stopped) as turn:
                final_state = get_app_graph().invoke(initial_state, config=cfg)
                turn.mode = final_state.get("mode")
            resp = _chat_response(final_state, effective_thread_id, force_mode, provider, model, security_mode, sess)
            if not incognito and not sess.is_stopped():
                thread_store.save_assistant_message(effective_thread_id, resp.model_dump())
                if needs_title_generation:
                    threading.Thread(
                        target=thread_store.generate_and_save_title,
                        args=(effective_thread_id, title_prompt, model, input_tag, provider),
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
                            args=(effective_thread_id, title_prompt, model, input_tag, provider),
                            daemon=True
                        ).start()
            sess.put(None)

    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(worker,))
    t.start()
    return sess


def stop_turn(thread_id: str) -> bool:
    """Ferma il turno del thread e lascia nella conversazione la nota dell'interruzione. False se non c'è un turno."""
    sess = get_session(thread_id)
    if not sess:
        return False
    sess.stop()
    thread_store.save_assistant_message(thread_id, {"response": "[Esecuzione interrotta dall'utente]", "error": False})
    return True


def run_agent_flow_stream(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: Union[str, bool] = "auto", request: Optional[Request] = None, images: Optional[List[str]] = None, security_mode: str = "normal", sensitivity: Optional[str] = None, provider: Optional[str] = None):
    """Turno web: `start_turn` più la parte SSE, che si iscrive alla sessione e inoltra gli eventi."""
    sess = start_turn(task, thread_id, force_mode=force_mode, execute=execute, reasoning_budget=reasoning_budget, model=model,
                      incognito=incognito, web_search=web_search, images=images, security_mode=security_mode, sensitivity=sensitivity,
                      provider=provider)
    effective_thread_id = sess.thread_id

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
