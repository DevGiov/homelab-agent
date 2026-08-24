import asyncio
import contextvars
import json
import queue
import sqlite3
import threading
import time
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader

import audit_log
import config
import letta_client
import thread_store
from graph import build_graph, stream_queue
from providers import (
    get_active_model_name,
    get_active_provider_name,
    list_provider_models,
    list_providers_info,
    set_active_provider,
)
from schemas import (
    AddMemoryRequest,
    ChatRequest,
    ChatResponse,
    ClearMemoryResponse,
    MemoryItem,
    MemoryListResponse,
    ProviderInfo,
    ProviderModelsResponse,
    ProvidersResponse,
    SetDefaultProviderRequest,
    ThreadSummary,
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

def run_agent_flow(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False) -> ChatResponse:
    effective_thread_id = thread_id or f"thread_{int(time.time() * 1000)}"
    initial_state = {
        "task": task,
        "thread_id": effective_thread_id,
        "force_mode": force_mode,
        "reasoning_budget": reasoning_budget,
        "model": model,
        "execute": execute,
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
        "incognito": incognito
    }

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

        resp = ChatResponse(
            thread_id=effective_thread_id,
            mode=mode,
            response=response_text,
            tool_used=tool_used,
            plan_steps=plan_steps,
            plan_structure=plan_structure,
            execution_trace=execution_trace,
            rollback_trace=rollback_trace,
            reasoning_content=reasoning_content
        )

        # Salva atomico del turno nello store SQLite solo se non in modalità incognito
        if not incognito:
            thread_store.save_turn(effective_thread_id, task, resp.model_dump())

        return resp

    except Exception as e:
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
    """Elenca i modelli disponibili per il provider specificato."""
    try:
        models = list_provider_models(name)
        return ProviderModelsResponse(provider=name, models=models)
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
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito)

@api.post("/v1/ask", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def ask_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="ask", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito)

@api.post("/v1/act", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def act_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="act", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito)

@api.post("/v1/plan", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def plan_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode="plan", execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito)

@api.post("/v1/invoke", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def invoke_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito)

def run_agent_flow_stream(task: str, thread_id: Optional[str], force_mode: Optional[str] = None, execute: bool = False, reasoning_budget: Optional[int] = None, model: Optional[str] = None, incognito: bool = False):
    effective_thread_id = thread_id or f"thread_{int(time.time() * 1000)}"
    initial_state = {
        "task": task,
        "thread_id": effective_thread_id,
        "force_mode": force_mode,
        "reasoning_budget": reasoning_budget,
        "model": model,
        "execute": execute,
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
        "incognito": incognito
    }

    cfg = {"configurable": {"thread_id": effective_thread_id}}
    q = queue.Queue()
    stream_queue.set(q)

    def worker():
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

            resp = ChatResponse(
                thread_id=effective_thread_id,
                mode=mode,
                response=response_text,
                tool_used=tool_used,
                plan_steps=plan_steps,
                plan_structure=plan_structure,
                execution_trace=execution_trace,
                rollback_trace=rollback_trace,
                reasoning_content=reasoning_content
            )
            if not incognito:
                thread_store.save_turn(effective_thread_id, task, resp.model_dump())
            q.put({"type": "final", "response": resp.model_dump()})
        except Exception as e:
            q.put({"type": "error", "error": str(e)})
        finally:
            q.put(None)

    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(worker,))
    t.start()

    def event_generator():
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@api.post("/v1/invoke_stream", dependencies=[Depends(verify_api_key)])
@_limit(config.RATE_LIMIT)
async def invoke_stream_endpoint(req: ChatRequest, request: Request = None):
    return run_agent_flow_stream(req.input, req.thread_id, force_mode=req.force_mode, execute=req.execute, reasoning_budget=req.reasoning_budget, model=req.model, incognito=req.incognito)

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
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT thread_id, COUNT(*) FROM checkpoints GROUP BY thread_id ORDER BY rowid DESC")
        rows = cursor.fetchall()
        conn.close()

        summaries = []
        for tid, count in rows:
            if not tid:
                continue
            last_msg = thread_store.get_last_message(tid)

            # Se non c'è last_message, tenta backfill da LangGraph per popolare lo store
            if last_msg is None and count > 0:
                backfilled = thread_store.backfill_from_state_history(tid, app_graph)
                if backfilled:
                    last_msg = thread_store.get_last_message(tid)

            summaries.append(ThreadSummary(
                thread_id=tid,
                last_message=last_msg,
                checkpoint_count=count
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

        # 3. Letta come fonte supplementare opzionale (mai bloccante)
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
            "agent_id": agent_id,
            "checkpoint_count": count,
            "messages": stored_messages,
            "letta_messages": clean_messages
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get thread details: {str(e)}")

@api.delete("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def delete_single_thread(thread_id: str):
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        deleted_rows = cursor.rowcount
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

@api.post("/v1/approvals/{request_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_request(request_id: str):
    """Approva una richiesta ed esegue immediatamente il tool."""
    import guardrails
    from registry.manager import get_registry_manager
    req = guardrails.resolve_approval(request_id, approved=True)
    if req is None:
        raise HTTPException(status_code=404, detail=f"Richiesta '{request_id}' non trovata o già risolta")
    if req.status == "expired":
        raise HTTPException(status_code=410, detail="Richiesta scaduta")
    result = get_registry_manager().execute_approved_tool(request_id)
    return {"request_id": request_id, "status": "approved", "result": result}

@api.post("/v1/approvals/{request_id}/deny", dependencies=[Depends(verify_api_key)])
async def deny_request(request_id: str):
    """Nega una richiesta di approvazione."""
    import guardrails
    req = guardrails.resolve_approval(request_id, approved=False)
    if req is None:
        raise HTTPException(status_code=404, detail=f"Richiesta '{request_id}' non trovata o già risolta")
    return {"request_id": request_id, "status": "denied", "tool_name": req.tool_name}


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


