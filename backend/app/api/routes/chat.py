"""Esecuzione dell'agente: chat sincrona, streaming SSE e controlli dello stream."""
import asyncio
import json
import logging
import queue
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.stream_session import (
    get_session,
)
from app.api.agent_runner import run_agent_flow, run_agent_flow_stream, stop_turn, turn_selection
from app.api.deps import rate_limited, verify_api_key
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ThreadControlRequest,
)
from app.llm.providers import ProviderUnavailableError, require_provider

logger = logging.getLogger("api")

router = APIRouter(tags=["chat"])


def _selection(req: ChatRequest) -> Tuple[str, Optional[str]]:
    """Provider e modello della richiesta (docs/providers/PROVIDERS_DESIGN.md, 5.8.1 e 5.8.6). Senza né provider né
    modello, una conversazione esistente usa la coppia salvata con lei; altrimenti, o senza coppia salvata, vale il
    provider predefinito. Un provider disattivato, incompleto o eliminato: 409, senza ripiegare da soli su un altro."""
    provider, model = turn_selection(req.thread_id, req.provider, req.model)
    try:
        return require_provider(provider), model
    except ProviderUnavailableError as e:
        raise HTTPException(status_code=409, detail={"code": "provider_disabled", "message": str(e)}) from e


def _run(req: ChatRequest, force_mode: Optional[str]) -> ChatResponse:
    provider, model = _selection(req)
    return run_agent_flow(req.input, req.thread_id, force_mode=force_mode, execute=req.execute,
                          reasoning_budget=req.reasoning_budget, model=model, incognito=req.incognito,
                          web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal",
                          sensitivity=req.sensitivity, provider=provider)


@router.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def chat_endpoint(req: ChatRequest, request: Request = None):
    return _run(req, req.force_mode)

@router.post("/v1/ask", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def ask_endpoint(req: ChatRequest, request: Request = None):
    return _run(req, "ask")

@router.post("/v1/act", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def act_endpoint(req: ChatRequest, request: Request = None):
    return _run(req, "act")

@router.post("/v1/plan", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def plan_endpoint(req: ChatRequest, request: Request = None):
    return _run(req, "plan")

@router.post("/v1/invoke", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def invoke_endpoint(req: ChatRequest, request: Request = None):
    return _run(req, req.force_mode)

@router.post("/v1/invoke_stream", dependencies=[Depends(verify_api_key)])
@rate_limited
async def invoke_stream_endpoint(req: ChatRequest, request: Request = None):
    provider, model = _selection(req)
    return run_agent_flow_stream(
        req.input,
        req.thread_id,
        force_mode=req.force_mode,
        execute=req.execute,
        reasoning_budget=req.reasoning_budget,
        model=model,
        incognito=req.incognito,
        web_search=req.web_search,
        request=request,
        images=req.images,
        security_mode=req.security_mode or "normal",
        sensitivity=req.sensitivity,
        provider=provider,
    )

@router.get("/v1/threads/{thread_id}/stream", dependencies=[Depends(verify_api_key)])
async def thread_stream_endpoint(thread_id: str, request: Request):
    """Permette a client riconnessi o a dispositivi differenti di agganciarsi allo streaming in corso."""
    sess = get_session(thread_id)
    if not sess or not sess.is_active():
        async def empty_gen():
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    async def event_generator():
        sub_q = sess.subscribe()
        try:
            # Invia subito snapshot sync con tutto lo stato accumulato
            yield f"data: {json.dumps(sess.get_snapshot(), ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    logger.info(f"Client SSE riconnesso si è disconnesso per thread '{thread_id}'. L'elaborazione continua.")
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

@router.post("/v1/chat/stop", dependencies=[Depends(verify_api_key)])
async def chat_stop_endpoint(req: ThreadControlRequest):
    if stop_turn(req.thread_id):
        return {"status": "ok", "message": "Stream stopped"}
    return {"status": "not_found", "message": "No active stream for thread"}

@router.post("/v1/chat/pause", dependencies=[Depends(verify_api_key)])
async def chat_pause_endpoint(req: ThreadControlRequest):
    sess = get_session(req.thread_id)
    if sess:
        sess.pause()
        return {"status": "ok", "message": "Stream paused"}
    return {"status": "not_found", "message": "No active stream for thread"}

@router.post("/v1/chat/resume", dependencies=[Depends(verify_api_key)])
async def chat_resume_endpoint(req: ThreadControlRequest):
    sess = get_session(req.thread_id)
    if sess:
        sess.resume()
        return {"status": "ok", "message": "Stream resumed"}
    return {"status": "not_found", "message": "No active stream for thread"}
