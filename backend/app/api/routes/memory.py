"""Memoria vettoriale: fatti salienti e loro gestione."""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import verify_api_key
from app.api.schemas import (
    AddMemoryRequest,
    ClearMemoryResponse,
    MemoryItem,
    MemoryListResponse,
)
from app.core.config import settings
from app.memory import letta_client

router = APIRouter(tags=["memory"])


# --- Gestione Memoria (Fase 4.3 & Controllo Frontend) ---

@router.get("/v1/memory", response_model=MemoryListResponse, dependencies=[Depends(verify_api_key)])
async def get_memories(kind: Optional[str] = "fact", limit: int = 100, offset: int = 0):
    """Restituisce i fatti salienti salvati nella memoria vettoriale."""
    from app.memory import vector_store
    items = vector_store.list_memories(kind=kind, limit=limit, offset=offset)
    total = vector_store.count_memory(kind=kind)
    return {"memories": items, "total": total}

@router.get("/v1/memory/search", dependencies=[Depends(verify_api_key)])
async def search_memories_endpoint(query: str, kind: Optional[str] = None, k: int = 5):
    """Esegue una ricerca semantica nel Vector Store (fatti e/o documenti KB)."""
    from app.memory import vector_store
    if not query.strip():
        return {"results": []}
    hits = vector_store.search_memory(query.strip(), k=k, kind=kind)
    return {"results": hits}


@router.post("/v1/memory", response_model=MemoryItem, dependencies=[Depends(verify_api_key)])
async def add_single_memory(req: AddMemoryRequest):
    """Aggiunge manualmente un fatto alla memoria vettoriale a lungo termine."""
    from app.memory import vector_store
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

@router.delete("/v1/memory/{memory_id}", dependencies=[Depends(verify_api_key)])
async def delete_single_memory(memory_id: int):
    """Elimina un singolo fatto saliente per ID."""
    from app.memory import vector_store
    success = vector_store.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Fatto con ID {memory_id} non trovato")
    return {"status": "deleted", "id": memory_id}

@router.delete("/v1/memory", response_model=ClearMemoryResponse, dependencies=[Depends(verify_api_key)])
async def clear_all_memory(kind: Optional[str] = None):
    """
    Cancella l'intera memoria:
    1. Svuota la tabella vettoriale SQLite (vec_memory e vec_memory_idx)
    2. Cancella tutti gli agent Letta su CT 102
    3. Rimuove i file locali di summary e fatti salienti in backend/memory/
    """
    import glob

    from app.memory import vector_store
    deleted_vec = vector_store.clear_all_memories(kind=kind)
    deleted_letta = 0
    try:
        deleted_letta = letta_client.delete_all_threads()
    except Exception:
        pass

    # Rimuovi file locali di summary e fatti salienti
    mem_dir = settings.memory_dir
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
