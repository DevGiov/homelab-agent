"""Provider LLM e gestione dei modelli."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import verify_api_key
from app.api.schemas import (
    LoadModelRequest,
    ModelDetail,
    ProviderInfo,
    ProviderModelsResponse,
    ProvidersResponse,
    SetDefaultProviderRequest,
)
from app.core.config import settings
from app.llm.providers import (
    get_active_model_name,
    get_active_provider_name,
    list_provider_models,
    list_provider_models_with_details,
    list_providers_info,
    load_provider_model,
    model_status_changes,
    server_root,
    set_active_provider,
)

router = APIRouter(tags=["providers"])


# --- Gestione Provider e Modelli LLM ---

@router.get("/v1/providers", response_model=ProvidersResponse, dependencies=[Depends(verify_api_key)])
async def get_providers():
    """Restituisce la lista di provider registrati con health e modello attivo."""
    return ProvidersResponse(
        active_provider=get_active_provider_name(),
        active_model=get_active_model_name(),
        providers=[ProviderInfo(**p) for p in list_providers_info()]
    )

@router.get("/v1/providers/{name}/models", response_model=ProviderModelsResponse, dependencies=[Depends(verify_api_key)])
async def get_provider_models(name: str):
    """Elenca i modelli disponibili per il provider specificato con dettagli multimodali."""
    try:
        models = list_provider_models(name)
        details = list_provider_models_with_details(name)
        models_detail = [ModelDetail(**d) for d in details]
        return ProviderModelsResponse(provider=name, models=models, models_detail=models_detail)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore recupero modelli provider '{name}': {e}") from e

@router.put("/v1/providers/default", dependencies=[Depends(verify_api_key)])
async def set_default_provider_endpoint(req: SetDefaultProviderRequest):
    """Imposta il provider e/o il modello di default a runtime."""
    try:
        res = set_active_provider(req.provider, req.model)
        return {"status": "ok", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.post("/v1/providers/{name}/models/load", dependencies=[Depends(verify_api_key)])
async def load_provider_model_endpoint(name: str, req: LoadModelRequest):
    """Carica un modello in VRAM per il provider specificato."""
    try:
        res = load_provider_model(name, req.model)
        return {"status": "ok", "provider": name, "model": req.model, "result": res}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante il caricamento del modello '{req.model}': {e}") from e

@router.get("/v1/models/events")
async def models_events_endpoint():
    """Cambi di stato dei modelli in tempo reale, ricavati dagli eventi di llama-swap (/api/events)."""
    import httpx
    url = f"{server_root(settings.llama_cpp_url)}/api/events"

    async def sse_stream():
        known = {}
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as resp:
                    async for line in resp.aiter_lines():
                        for change in model_status_changes(line, known):
                            yield f"data: {json.dumps(change)}\n\n"
        except Exception:
            pass

    return StreamingResponse(sse_stream(), media_type="text/event-stream")
