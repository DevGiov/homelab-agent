"""Knowledge base: documenti indicizzati e ricerca."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import verify_api_key

router = APIRouter(tags=["kb"])


# --- Knowledge Base (Fase 2.3) ---

@router.get("/v1/kb/documents", dependencies=[Depends(verify_api_key)])
async def kb_list_documents():
    """Elenca i documenti indicizzati nella knowledge base."""
    from app.memory.knowledge_base import list_documents
    return {"documents": list_documents()}

@router.post("/v1/kb/documents", dependencies=[Depends(verify_api_key)])
async def kb_upload_document(request: Request):
    """Upload e indicizzazione di un documento (.md, .txt, .pdf) nella KB.

    Accetta multipart/form-data con campo 'file' oppure JSON {"filename", "content"}.
    """
    from app.memory import knowledge_base
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingesta fallita: {e}") from e

@router.delete("/v1/kb/documents/{filename}", dependencies=[Depends(verify_api_key)])
async def kb_delete_document(filename: str):
    """Elimina un documento dalla knowledge base."""
    from app.memory.knowledge_base import delete_document
    deleted = delete_document(filename)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Documento '{filename}' non trovato in KB")
    return {"status": "deleted", "filename": filename, "chunks_deleted": deleted}

@router.get("/v1/kb/search", dependencies=[Depends(verify_api_key)])
async def kb_search(query: str, k: int = 5):
    """Ricerca semantica nella knowledge base."""
    from app.memory.knowledge_base import search_knowledge
    return {"results": search_knowledge(query, k=max(1, min(k, 20)))}
