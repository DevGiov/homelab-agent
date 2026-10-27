"""Esecuzione dell'agente: chat sincrona, streaming SSE e controlli dello stream."""
import asyncio
import json
import logging
import queue

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agent.stream_session import (
    get_session,
)
from app.api.agent_runner import run_agent_flow, run_agent_flow_stream
from app.api.deps import rate_limited, verify_api_key
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ThreadControlRequest,
)
from app.memory import thread_store

logger = logging.getLogger("api")

router = APIRouter(tags=["chat"])


@router.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def chat_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@router.post("/v1/ask", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def ask_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="ask", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@router.post("/v1/act", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def act_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="act", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@router.post("/v1/plan", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def plan_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="plan", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@router.post("/v1/invoke", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@rate_limited
def invoke_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@router.post("/v1/invoke_stream", dependencies=[Depends(verify_api_key)])
@rate_limited
async def invoke_stream_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow_stream(
        req.input,
        req.thread_id,
        force_mode=req.force_mode,
        execute=req.execute,
        reasoning_budget=req.reasoning_budget,
        model=req.model,
        incognito=req.incognito,
        web_search=req.web_search,
        request=request,
        images=req.images,
        security_mode=req.security_mode or "normal",
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
    sess = get_session(req.thread_id)
    if sess:
        sess.stop()
        thread_store.save_assistant_message(req.thread_id, {
            "response": "[Esecuzione interrotta dall'utente]",
            "error": False
        })
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
