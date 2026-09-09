import asyncio
import base64
import contextvars
import json
import logging
import queue
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import APIKeyHeader

import audit_log
import config
import image_utils
import letta_client
import thread_store
from graph import _call_llm, build_graph, stream_queue, stream_reasoning_phase_count
from text_utils import clean_synthesis_content
from providers import (
    get_active_model_name,
    get_active_provider_name,
    list_provider_models,
    list_provider_models_with_details,
    list_providers_info,
    set_active_provider,
)
from schemas import (
    AddMemoryRequest,
    ChatRequest,
    ChatResponse,
    ClearMemoryResponse,
    ImageUploadResponse,
    MemoryItem,
    MemoryListResponse,
    ModelDetail,
    ProviderInfo,
    ProviderModelsResponse,
    ProvidersResponse,
    SetDefaultProviderRequest,
    SetThreadTitleRequest,
    SaveVersionsDataRequest,
    SwitchVersionRequest,
    ThreadControlRequest,
    ThreadSummary,
    ResolveApprovalRequest,
)
from stream_session import (
    create_session,
    current_session_var,
    get_session,
    remove_session,
)

# --- Fase 0.1: fail-fast se l'auth non è configurata ---
config.get_settings().validate_security()

app_graph = build_graph()

api = FastAPI(
    title="Home Lab Agent API",
    description="FastAPI service exposing LangGraph Agent with MetaMCP tools, Letta persistent memory, and SQLite Checkpointing",
    version="1.0"
)

# --- Fase 0.1: CORS ristretto alle origini configurate ---
api.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Fase 0.2: rate limiting ---
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    api.state.limiter = limiter
    api.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    _RATE_LIMIT_ENABLED = True
except ImportError:
    limiter = None
    _RATE_LIMIT_ENABLED = False

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    expected_key = config.API_SECRET_KEY.strip()
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return x_api_key

def run_agent_flow(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: bool = False, images: Optional[List[str]] = None, security_mode: str = "normal") -> ChatResponse:
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
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
        "incognito": incognito,
        "security_mode": security_mode,
    }

    # Salva immediatamente il messaggio dell'utente nello store SQLite
    if not incognito:
        thread_store.save_user_message(effective_thread_id, task, images=images)
        if not thread_store.get_thread_title(effective_thread_id):
            title_prompt = task.strip() if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
            threading.Thread(
                target=thread_store.generate_and_save_title,
                args=(effective_thread_id, title_prompt),
                daemon=True
            ).start()

    cfg = {"configurable": {"thread_id": effective_thread_id}}
    try:
        final_state = app_graph.invoke(initial_state, config=cfg)

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

        t_title = thread_store.get_thread_title(effective_thread_id)
        resp = ChatResponse(
            thread_id=effective_thread_id,
            mode=mode,
            response=response_text,
            tool_used=tool_used,
            plan_steps=plan_steps,
            plan_structure=plan_structure,
            execution_trace=execution_trace,
            rollback_trace=rollback_trace,
            reasoning_content=reasoning_content,
            web_prefetch=web_prefetch,
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

        return resp

    except Exception as e:
        if not incognito:
            thread_store.save_assistant_message(effective_thread_id, {
                "response": f"[Errore durante l'esecuzione: {str(e)}]",
                "error": True
            })
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")


@api.get("/v1/health")
async def health():
    return {"status": "ok"}

@api.get("/v1/status", dependencies=[Depends(verify_api_key)])
async def status():
    """Health check aggregato dei servizi esterni (Fase 1.4). Mai bloccante."""
    import httpx

    from providers import list_providers

    async def _ping(name: str, url: str, headers: dict = None):
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                res = await client.get(url, headers=headers)
                return {"name": name, "url": url, "ok": res.status_code == 200, "status_code": res.status_code}
        except Exception as e:
            return {"name": name, "url": url, "ok": False, "error": str(e)[:120]}

    letta_headers = {"Authorization": f"Bearer {config.LETTA_API_KEY}"} if config.LETTA_API_KEY else {}
    results = await asyncio.gather(
        _ping("llamacpp", f"{config.LLAMA_CPP_URL.rstrip('/')}/models"),
        _ping("metamcp", config.METAMCP_URL_HTTP),
        _ping("letta", f"{config.LETTA_URL.rstrip('/')}/v1/agents/", headers=letta_headers),
        return_exceptions=True,
    )
    services = [r for r in results if isinstance(r, dict)]
    providers_status = list_providers()
    return {
        "status": "ok" if all(s["ok"] for s in services) else "degraded",
        "services": services,
        "providers": providers_status,
    }

# --- Gestione Provider e Modelli LLM ---

@api.get("/v1/providers", response_model=ProvidersResponse, dependencies=[Depends(verify_api_key)])
async def get_providers():
    """Restituisce la lista di provider registrati con health e modello attivo."""
    return ProvidersResponse(
        active_provider=get_active_provider_name(),
        active_model=get_active_model_name(),
        providers=[ProviderInfo(**p) for p in list_providers_info()]
    )

@api.get("/v1/providers/{name}/models", response_model=ProviderModelsResponse, dependencies=[Depends(verify_api_key)])
async def get_provider_models(name: str):
    """Elenca i modelli disponibili per il provider specificato con dettagli multimodali."""
    try:
        models = list_provider_models(name)
        details = list_provider_models_with_details(name)
        models_detail = [ModelDetail(**d) for d in details]
        return ProviderModelsResponse(provider=name, models=models, models_detail=models_detail)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore recupero modelli provider '{name}': {e}")

@api.put("/v1/providers/default", dependencies=[Depends(verify_api_key)])
async def set_default_provider_endpoint(req: SetDefaultProviderRequest):
    """Imposta il provider e/o il modello di default a runtime."""
    try:
        res = set_active_provider(req.provider, req.model)
        return {"status": "ok", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

def _limit(rate: str):
    """Decorator di rate limiting condizionale (no-op se slowapi non è installato)."""
    if _RATE_LIMIT_ENABLED and limiter:
        return limiter.limit(config.RATE_LIMIT)
    def _noop(fn):
        return fn
    return _noop

@api.post("/v1/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def chat_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@api.post("/v1/ask", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def ask_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="ask", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@api.post("/v1/act", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def act_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="act", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@api.post("/v1/plan", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def plan_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="plan", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

@api.post("/v1/invoke", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def invoke_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito, web_search=req.web_search, images=req.images, security_mode=req.security_mode or "normal")

# Gestione upload file multimodali
import os
if os.path.exists("/data") and os.access("/data", os.W_OK):
    UPLOAD_DIR = Path("/data/uploads")
else:
    UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@api.post("/v1/upload", response_model=ImageUploadResponse, dependencies=[Depends(verify_api_key)])
async def upload_file_endpoint(file: UploadFile = File(...)):
    """Carica un'immagine per utilizzo multimodale, salvandola localmente e restituendo URL e base64 data_url."""
    filename = file.filename or "image.jpg"
    content_type = file.content_type or ""

    if not image_utils.is_supported_image(filename=filename, content_type=content_type):
        raise HTTPException(status_code=400, detail="Solo file di tipo immagine sono supportati.")

    contents = await file.read()
    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Dimensione massima file superata (limite 25MB).")

    # Ottimizza, orienta EXIF, ridimensiona a max 2048px e transcodifica HEIC/HEIF a JPEG
    try:
        opt_bytes, mime, w, h = image_utils.optimize_image_bytes(
            contents,
            max_dimension=2048,
            quality=85,
            force_jpeg=image_utils.is_heic_or_heif(filename=filename, content_type=content_type, raw_bytes=contents),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossibile elaborare l'immagine caricata: {e}")

    ext = ".jpg" if mime == "image/jpeg" else (Path(filename).suffix or ".jpg")
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / safe_name

    with open(file_path, "wb") as f:
        f.write(opt_bytes)

    encoded_b64 = base64.b64encode(opt_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{encoded_b64}"

    return ImageUploadResponse(
        url=f"/v1/uploads/{safe_name}",
        data_url=data_url,
        filename=safe_name,
        width=w,
        height=h,
    )

@api.get("/v1/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """Restituisce un file immagine caricato con intestazioni di sicurezza."""
    safe_filename = Path(filename).name
    file_path = UPLOAD_DIR / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File non trovato.")

    return FileResponse(
        str(file_path),
        headers={"X-Content-Type-Options": "nosniff"}
    )

def run_agent_flow_stream(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False, web_search: bool = False, request: Optional[Request] = None, images: Optional[List[str]] = None, security_mode: str = "normal"):
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
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
        "incognito": incognito,
        "security_mode": security_mode,
    }

    # Salva immediatamente il messaggio dell'utente nello store SQLite
    if not incognito:
        thread_store.save_user_message(effective_thread_id, task, images=images)
        if not thread_store.get_thread_title(effective_thread_id):
            title_prompt = task.strip() if (task and task.strip()) else ("Analisi immagine" if images else "Nuova conversazione")
            threading.Thread(
                target=thread_store.generate_and_save_title,
                args=(effective_thread_id, title_prompt),
                daemon=True
            ).start()

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
                final_state = app_graph.invoke(initial_state, config=cfg)
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
                resp = ChatResponse(
                    thread_id=effective_thread_id,
                    mode=mode,
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
                    logging.getLogger("api").info(f"Client SSE disconnesso per thread '{effective_thread_id}'. L'elaborazione continua in background.")
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

@api.post("/v1/invoke_stream", dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
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

@api.get("/v1/threads/{thread_id}/stream", dependencies=[Depends(verify_api_key)])
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
                    logging.getLogger("api").info(f"Client SSE riconnesso si è disconnesso per thread '{thread_id}'. L'elaborazione continua.")
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

@api.post("/v1/chat/stop", dependencies=[Depends(verify_api_key)])
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

@api.post("/v1/chat/pause", dependencies=[Depends(verify_api_key)])
async def chat_pause_endpoint(req: ThreadControlRequest):
    sess = get_session(req.thread_id)
    if sess:
        sess.pause()
        return {"status": "ok", "message": "Stream paused"}
    return {"status": "not_found", "message": "No active stream for thread"}

@api.post("/v1/chat/resume", dependencies=[Depends(verify_api_key)])
async def chat_resume_endpoint(req: ThreadControlRequest):
    sess = get_session(req.thread_id)
    if sess:
        sess.resume()
        return {"status": "ok", "message": "Stream resumed"}
    return {"status": "not_found", "message": "No active stream for thread"}

@api.get("/v1/audit", dependencies=[Depends(verify_api_key)])
async def get_audit_log(limit: int = 100, thread_id: Optional[str] = None):
    """Restituisce le ultime voci dell'audit log dei tool call (Fase 0.4)."""
    limit = max(1, min(limit, 500))
    return {"entries": audit_log.get_recent(limit=limit, thread_id=thread_id)}

# --- Knowledge Base (Fase 2.3) ---

@api.get("/v1/kb/documents", dependencies=[Depends(verify_api_key)])
async def kb_list_documents():
    """Elenca i documenti indicizzati nella knowledge base."""
    from knowledge_base import list_documents
    return {"documents": list_documents()}

@api.post("/v1/kb/documents", dependencies=[Depends(verify_api_key)])
async def kb_upload_document(request: Request):
    """Upload e indicizzazione di un documento (.md, .txt, .pdf) nella KB.

    Accetta multipart/form-data con campo 'file' oppure JSON {"filename", "content"}.
    """
    import knowledge_base
    content_type = request.headers.get("content-type", "")

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                raise HTTPException(status_code=400, detail="Campo 'file' mancante nel form")
            filename = upload.filename
            content_bytes = await upload.read()
            stats = knowledge_base.ingest_document(filename, content_bytes=content_bytes)
        else:
            body = await request.json()
            filename = body.get("filename")
            content = body.get("content")
            if not filename or content is None:
                raise HTTPException(status_code=400, detail="Servono 'filename' e 'content'")
            stats = knowledge_base.ingest_document(filename, text_content=content)
        return {"status": "ingested", **stats}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingesta fallita: {e}")

@api.delete("/v1/kb/documents/{filename}", dependencies=[Depends(verify_api_key)])
async def kb_delete_document(filename: str):
    """Elimina un documento dalla knowledge base."""
    from knowledge_base import delete_document
    deleted = delete_document(filename)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Documento '{filename}' non trovato in KB")
    return {"status": "deleted", "filename": filename, "chunks_deleted": deleted}

@api.get("/v1/kb/search", dependencies=[Depends(verify_api_key)])
async def kb_search(query: str, k: int = 5):
    """Ricerca semantica nella knowledge base."""
    from knowledge_base import search_knowledge
    return {"results": search_knowledge(query, k=max(1, min(k, 20)))}


@api.get("/v1/threads", response_model=List[ThreadSummary], dependencies=[Depends(verify_api_key)])
async def list_threads():
    try:
        thread_store.init_db()
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT thread_id, MAX(cp_count) as checkpoint_count, MAX(last_activity) as sort_key
            FROM (
                SELECT thread_id, COUNT(*) as cp_count, MAX(rowid) as last_activity FROM checkpoints GROUP BY thread_id
                UNION ALL
                SELECT thread_id, 0 as cp_count, MAX(rowid) as last_activity FROM thread_messages GROUP BY thread_id
            )
            WHERE thread_id IS NOT NULL AND thread_id != ''
            GROUP BY thread_id
            ORDER BY sort_key DESC
        """)
        rows = cursor.fetchall()

        cursor.execute("SELECT thread_id, title FROM thread_metadata")
        titles_map = dict(cursor.fetchall())
        conn.close()

        summaries = []
        found_tids = set()
        for row in rows:
            tid = row[0]
            count = row[1]
            if not tid:
                continue
            found_tids.add(tid)
            last_msg = thread_store.get_last_message(tid)

            # Se non c'è last_message, tenta backfill da LangGraph per popolare lo store
            if last_msg is None and count > 0:
                backfilled = thread_store.backfill_from_state_history(tid, app_graph)
                if backfilled:
                    last_msg = thread_store.get_last_message(tid)

            sess = get_session(tid)
            is_active = sess is not None and sess.is_active()

            summaries.append(ThreadSummary(
                thread_id=tid,
                title=titles_map.get(tid),
                last_message=last_msg,
                checkpoint_count=count,
                is_active=is_active
            ))

        # Aggiungi eventuali sessioni attive non ancora persistite in SQLite
        from stream_session import _active_sessions, _sessions_lock
        with _sessions_lock:
            active_items = [(tid, s) for tid, s in _active_sessions.items() if s.is_active()]
        for atid, asess in active_items:
            if atid not in found_tids:
                summaries.insert(0, ThreadSummary(
                    thread_id=atid,
                    title=titles_map.get(atid),
                    last_message=asess.task,
                    checkpoint_count=0,
                    is_active=True
                ))

        return summaries
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list threads: {str(e)}")


@api.get("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def get_thread(thread_id: str):
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,))
        count = cursor.fetchone()[0]
        conn.close()

        # 1. Prova lo store locale (istantaneo)
        stored_messages = thread_store.get_thread_messages(thread_id)

        # 2. Se vuoto ma il thread ha checkpoint, ricostruisci da LangGraph state history
        if not stored_messages and count > 0:
            stored_messages = thread_store.backfill_from_state_history(thread_id, app_graph)

        # 3. Controlla se c'è una sessione attiva per questo thread
        sess = get_session(thread_id)
        is_active = sess is not None and sess.is_active()
        is_paused = sess.is_paused() if sess else False
        active_snapshot = sess.get_snapshot() if is_active else None

        # Se la sessione è attiva, sintetizza lo stato in tempo reale nei messaggi
        if is_active:
            if not stored_messages and sess.task:
                stored_messages.append({
                    "id": f"user_live_{thread_id}",
                    "sender": "user",
                    "content": sess.task,
                    "timestamp": time.strftime("%H:%M")
                })
            last_msg = stored_messages[-1] if stored_messages else None
            if not last_msg or last_msg.get("sender") == "user":
                stored_messages.append({
                    "id": f"ast_live_{thread_id}",
                    "sender": "assistant",
                    "content": sess.partial_content or "",
                    "reasoning_content": sess.reasoning_content or "",
                    "mode": sess.mode or "plan",
                    "tool_used": sess.active_tool,
                    "plan_steps": sess.plan_steps,
                    "plan_structure": sess.plan_structure,
                    "execution_trace": sess.execution_trace,
                    "metrics": sess.get_metrics(),
                    "isRunning": True,
                    "timestamp": time.strftime("%H:%M")
                })

        # 4. Letta come fonte supplementare opzionale (mai bloccante)
        clean_messages = []
        agent_id = None
        try:
            agent_id = letta_client.create_thread(thread_id)
            if agent_id:
                raw_messages = letta_client.get_messages(agent_id)
                clean_messages = letta_client.filter_clean_messages(raw_messages) if raw_messages else []
        except Exception as letta_err:
            import logging
            logging.getLogger("api").warning(f"Letta non raggiungibile per thread '{thread_id}': {letta_err}")

        return {
            "thread_id": thread_id,
            "title": thread_store.get_thread_title(thread_id),
            "agent_id": agent_id,
            "checkpoint_count": count,
            "messages": stored_messages,
            "letta_messages": clean_messages,
            "is_active": is_active,
            "is_paused": is_paused,
            "active_snapshot": active_snapshot
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get thread details: {str(e)}")


@api.patch("/v1/threads/{thread_id}/title", dependencies=[Depends(verify_api_key)])
async def update_thread_title(thread_id: str, req: SetThreadTitleRequest):
    thread_store.set_thread_title(thread_id, req.title)
    return {"status": "ok", "thread_id": thread_id, "title": req.title}


@api.post("/v1/threads/{thread_id}/title/generate", dependencies=[Depends(verify_api_key)])
async def force_generate_thread_title(thread_id: str):
    last_msg = thread_store.get_last_message(thread_id) or "Nuova chat"
    title = thread_store.generate_and_save_title(thread_id, last_msg)
    return {"status": "ok", "thread_id": thread_id, "title": title}


@api.post("/v1/threads/{thread_id}/messages/{message_id}/version", dependencies=[Depends(verify_api_key)])
async def switch_message_version(thread_id: str, message_id: str, req: SwitchVersionRequest):
    thread_store.update_message_version(thread_id, message_id, req.version_index)
    return {"status": "ok", "thread_id": thread_id, "message_id": message_id, "version_index": req.version_index}


@api.post("/v1/threads/{thread_id}/messages/{message_id}/versions_data", dependencies=[Depends(verify_api_key)])
async def update_message_versions(thread_id: str, message_id: str, req: SaveVersionsDataRequest):
    thread_store.update_message_versions_data(thread_id, message_id, req.versions, req.version_index)
    return {"status": "ok", "thread_id": thread_id, "message_id": message_id}


@api.delete("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def delete_single_thread(thread_id: str):
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        deleted_rows = cursor.rowcount
        cursor.execute("DELETE FROM thread_metadata WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()

        thread_store.delete_thread_messages(thread_id)

        # Delete from Letta if agent exists (non-blocking)
        try:
            agent_id = letta_client.create_thread(thread_id)
            if agent_id:
                letta_client.delete_thread(agent_id)
        except Exception:
            pass

        return {"status": "deleted", "thread_id": thread_id, "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete thread '{thread_id}': {str(e)}")

@api.delete("/v1/threads", dependencies=[Depends(verify_api_key)])
async def delete_all_threads():
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints")
        deleted_rows = cursor.rowcount
        cursor.execute("DELETE FROM thread_metadata")
        conn.commit()
        conn.close()

        thread_store.clear_all_thread_messages()

        return {"status": "cleared", "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear threads: {str(e)}")

# --- Approval workflow (Fase 3.2) ---

@api.get("/v1/approvals", dependencies=[Depends(verify_api_key)])
async def list_approvals(thread_id: Optional[str] = None):
    """Elenca le richieste di approvazione tool pendenti."""
    import guardrails
    return {"pending": guardrails.get_pending_approvals(thread_id=thread_id)}

@api.post("/v1/approvals/{request_id}/resolve", dependencies=[Depends(verify_api_key)])
async def resolve_approval_endpoint(request_id: str, req_body: ResolveApprovalRequest):
    """
    Risolve una richiesta di approvazione tool con scope:
    - 'deny': rifiuta l'azione
    - 'approve': autorizza l'azione una tantum
    - 'approve_thread': autorizza per l'intera sessione/chat
    - 'approve_always': autorizza in modo permanente (tabella tool_permissions)
    """
    import guardrails
    from registry.manager import get_registry_manager

    action = req_body.action.lower().strip()
    req = guardrails.resolve_approval(request_id, action=action, resolved_by=req_body.resolved_by)
    if req is None:
        raise HTTPException(status_code=404, detail=f"Richiesta '{request_id}' non trovata o già risolta")
    if req.status == "expired":
        raise HTTPException(status_code=410, detail="Richiesta scaduta")

    if action in ("deny", "false", "refuse"):
        if req.thread_id:
            thread_store.save_assistant_message(req.thread_id, {
                "response": f"🛑 **Azione annullata**: L'esecuzione del tool `{req.tool_name}` è stata rifiutata dall'utente.",
                "tool_used": req.tool_name,
                "error": True
            })
        return {
            "request_id": request_id,
            "status": "denied",
            "tool_name": req.tool_name,
            "message": f"Azione per il tool '{req.tool_name}' rifiutata."
        }

    # Esecuzione del tool autorizzato
    result = get_registry_manager().execute_approved_tool(request_id)

    # Recupera task utente associato alla richiesta
    user_task = getattr(req, "task", None)
    if not user_task and req.thread_id:
        try:
            msgs = thread_store.get_thread_messages(req.thread_id)
            user_msgs = [m for m in msgs if m.get("sender") == "user"]
            if user_msgs:
                user_task = user_msgs[-1].get("content") or user_msgs[-1].get("text") or ""
        except Exception as e:
            logger.warning(f"Impossibile recuperare ultimo messaggio utente: {e}")

    # Sintesi LLM del risultato
    from registry.search_security import UNTRUSTED_CONTEXT_POLICY
    res_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
    obs_text = f"Tool '{req.tool_name}' con argomenti {json.dumps(req.arguments, ensure_ascii=False)} -> {res_str}"
    if len(obs_text) > 4000:
        obs_text = obs_text[:4000] + "\n... [output troncato per brevità]"

    summary_system_prompt = (
        f"Data e Ora Corrente del Sistema: {datetime.now().strftime('%A %d %B %Y, %H:%M:%S')}\n"
        f"Sei l'Agente AI dell'Homelab Proxmox VE. Sintetizza i risultati delle azioni in italiano.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}"
    )
    summary_prompt = (
        f"Richiesta originale dell'utente: '{user_task or 'Esegui il comando richiesto'}'\n\n"
        f"Risultato dell'azione autorizzata ed eseguita:\n{obs_text}\n\n"
        f"Fornisci una risposta finale completa, discorsiva e dettagliata in italiano. "
        f"Interpreta l'output del tool, rispondi direttamente alla richiesta dell'utente "
        f"e spiega chiaramente il risultato ottenuto (se vi sono errori come file o configurazioni mancanti o container inesistenti, indicalo chiaramente). "
        f"Rispondi in prosa naturale (nessun JSON grezzo come unica risposta): questa è la risposta per l'utente."
    )

    synthesized_text = ""
    try:
        syn_res = _call_llm(
            summary_prompt,
            system_prompt=summary_system_prompt,
            max_tokens=4096,
            stream_mode="none",
            reasoning_budget=0
        )
        raw_ans = syn_res.get("content", "") if syn_res else ""
        synthesized_text = clean_synthesis_content(raw_ans)
    except Exception as e:
        logger.warning(f"Errore durante la sintesi LLM post-approvazione: {e}")

    if not synthesized_text:
        res_preview = res_str[:1500] + ("\n... [troncato]" if len(res_str) > 1500 else "")
        synthesized_text = f"Tool `{req.tool_name}` approvato ed eseguito con successo.\n\n```json\n{res_preview}\n```"

    trace = [
        {
            "step_id": 1,
            "tool_name": req.tool_name,
            "args": req.arguments,
            "result": result,
            "reasoning": f"Tool autorizzato dall'utente ({action})"
        }
    ]

    if req.thread_id:
        thread_store.save_assistant_message(req.thread_id, {
            "response": synthesized_text,
            "tool_used": req.tool_name,
            "execution_trace": trace,
            "mode": req.mode or "act",
            "error": isinstance(result, dict) and bool(result.get("error"))
        })

    return {
        "request_id": request_id,
        "status": "approved",
        "action": action,
        "tool_name": req.tool_name,
        "arguments": req.arguments,
        "result": result,
        "response": synthesized_text,
        "execution_trace": trace
    }

@api.post("/v1/approvals/{request_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_request(request_id: str):
    """Retrocompatibilità: approva singola esecuzione."""
    return await resolve_approval_endpoint(request_id, ResolveApprovalRequest(action="approve"))

@api.post("/v1/approvals/{request_id}/deny", dependencies=[Depends(verify_api_key)])
async def deny_request(request_id: str):
    """Retrocompatibilità: nega esecuzione."""
    return await resolve_approval_endpoint(request_id, ResolveApprovalRequest(action="deny"))

@api.get("/v1/permissions", dependencies=[Depends(verify_api_key)])
async def get_permissions(thread_id: Optional[str] = None):
    """Elenca i permessi persistenti (ALWAYS) e quelli attivi per la sessione (THREAD)."""
    import permissions
    return permissions.list_granted_permissions(thread_id=thread_id)

@api.delete("/v1/permissions/{permission_id}", dependencies=[Depends(verify_api_key)])
async def delete_permission(permission_id: int):
    """Revoca un permesso persistente per ID."""
    import permissions
    success = permissions.revoke_permission(permission_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Permesso ID {permission_id} non trovato")
    return {"status": "ok", "revoked_id": permission_id}

@api.delete("/v1/threads/{thread_id}/permissions", dependencies=[Depends(verify_api_key)])
async def delete_thread_permissions(thread_id: str):
    """Revoca tutti i permessi temporanei di sessione per il thread specificato."""
    import permissions
    permissions.revoke_thread_permissions(thread_id)
    return {"status": "ok", "thread_id": thread_id, "message": "Permessi di sessione revocati"}


# --- Gestione Memoria (Fase 4.3 & Controllo Frontend) ---

@api.get("/v1/memory", response_model=MemoryListResponse, dependencies=[Depends(verify_api_key)])
async def get_memories(kind: Optional[str] = "fact", limit: int = 100, offset: int = 0):
    """Restituisce i fatti salienti salvati nella memoria vettoriale."""
    import vector_store
    items = vector_store.list_memories(kind=kind, limit=limit, offset=offset)
    total = vector_store.count_memory(kind=kind)
    return {"memories": items, "total": total}

@api.get("/v1/memory/search", dependencies=[Depends(verify_api_key)])
async def search_memories_endpoint(query: str, kind: Optional[str] = None, k: int = 5):
    """Esegue una ricerca semantica nel Vector Store (fatti e/o documenti KB)."""
    import vector_store
    if not query.strip():
        return {"results": []}
    hits = vector_store.search_memory(query.strip(), k=k, kind=kind)
    return {"results": hits}


@api.post("/v1/memory", response_model=MemoryItem, dependencies=[Depends(verify_api_key)])
async def add_single_memory(req: AddMemoryRequest):
    """Aggiunge manualmente un fatto alla memoria vettoriale a lungo termine."""
    import vector_store
    row_id = vector_store.add_memory(
        content=req.content,
        kind=req.kind,
        thread_id=req.thread_id,
        metadata=req.metadata
    )
    if row_id is None:
        raise HTTPException(status_code=400, detail="Impossibile aggiungere il fatto alla memoria")
    return {
        "id": row_id,
        "kind": req.kind,
        "thread_id": req.thread_id,
        "content": req.content,
        "metadata": req.metadata or {},
        "created_at": None
    }

@api.delete("/v1/memory/{memory_id}", dependencies=[Depends(verify_api_key)])
async def delete_single_memory(memory_id: int):
    """Elimina un singolo fatto saliente per ID."""
    import vector_store
    success = vector_store.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Fatto con ID {memory_id} non trovato")
    return {"status": "deleted", "id": memory_id}

@api.delete("/v1/memory", response_model=ClearMemoryResponse, dependencies=[Depends(verify_api_key)])
async def clear_all_memory(kind: Optional[str] = None):
    """
    Cancella l'intera memoria:
    1. Svuota la tabella vettoriale SQLite (vec_memory e vec_memory_idx)
    2. Cancella tutti gli agent Letta su CT 102
    3. Rimuove i file locali di summary e fatti salienti in backend/memory/
    """
    import glob
    import os
    import vector_store

    deleted_vec = vector_store.clear_all_memories(kind=kind)
    deleted_letta = 0
    try:
        deleted_letta = letta_client.delete_all_threads()
    except Exception:
        pass

    # Rimuovi file locali di summary e fatti salienti
    mem_dir = "/opt/homelab-agent/memory" if os.path.exists("/opt/homelab-agent/memory") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")
    if os.path.exists(mem_dir):
        for pattern in ["salient_facts_*.txt", "summary_*.txt"]:
            for fpath in glob.glob(os.path.join(mem_dir, pattern)):
                try:
                    os.remove(fpath)
                except Exception:
                    pass

    return {
        "deleted_count": deleted_vec,
        "letta_cleared": True,
        "message": f"Memoria azzerata con successo ({deleted_vec} record vettoriali, {deleted_letta} agent Letta eliminati)."
    }


