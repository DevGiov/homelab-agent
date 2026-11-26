"""Provider LLM gestiti dalla Web UI, catalogo dei modelli, prezzi e tetti di spesa.

Il contratto delle risposte è in docs/providers/PROVIDERS_DESIGN.md, 5.8.6. Tutte le route sono dell'utente, dietro
`verify_api_key`: nessun tool dell'agente le raggiunge. Le route con un percorso fisso (`settings`, `costs`,
`ceilings`) stanno prima di quelle con `{name}`, e quei nomi sono riservati: un provider non può chiamarsi così.
"""
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import verify_api_key
from app.api.schemas import (
    LoadModelRequest,
    ModelDetail,
    ModelPriceRequest,
    ProviderModelsResponse,
    SpendCeilingRequest,
)
from app.llm import costs, provider_config, providers
from app.llm.provider_config import ProviderConfigError
from app.llm.providers import (
    OpenAICompatProvider,
    list_provider_models,
    list_provider_models_with_details,
    load_provider_model,
    model_status_changes,
    registered_provider_names,
    server_root,
)

router = APIRouter(tags=["providers"])
# Ogni route dell'utente; non `/v1/models/events`, che un EventSource del browser apre senza header (come prima)
AUTH = [Depends(verify_api_key)]


class CreateProviderRequest(BaseModel):
    # I campi e le credenziali li controlla app.llm.provider_config, con messaggi che non ripetono mai un valore
    name: Any = None
    kind: Any = None
    display_name: Any = None
    fields: Optional[Dict[str, Any]] = None
    secrets: Optional[Dict[str, Any]] = None


class PatchProviderRequest(BaseModel):
    kind: Any = None
    display_name: Any = None
    enabled: Any = None
    fields: Optional[Dict[str, Any]] = None
    secrets: Optional[Dict[str, Any]] = None
    # Solo per il provider di ripiego che cambia indirizzo: il livello `private` passa al nuovo indirizzo
    confirm: bool = False


class ClearanceRequest(BaseModel):
    level: str
    confirm: bool = False


class ProviderSettingsRequest(BaseModel):
    default_provider: Optional[str] = None
    fallback_provider: Optional[str] = None


def _error(e: ProviderConfigError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ProviderConfigError as e:
        raise _error(e) from e


# --- Elenco, creazione, impostazioni (percorsi fissi) --------------------------------------------------

@router.get("/v1/providers", dependencies=AUTH)
def get_providers():
    """Tutti i provider: tipo, campi con l'origine, credenziali `{set, source}`, livello salvato ed effettivo."""
    return provider_config.list_view()


@router.post("/v1/providers", status_code=201, dependencies=AUTH)
def create_provider(req: CreateProviderRequest):
    """Un provider nuovo: nasce attivo e `public`."""
    return _call(provider_config.create, req.name, req.kind, req.display_name, req.fields, req.secrets)


@router.put("/v1/providers/settings", dependencies=AUTH)
def update_provider_settings(req: ProviderSettingsRequest):
    """Provider predefinito e provider di ripiego."""
    return _call(provider_config.update_settings, req.default_provider, req.fallback_provider)


# --- Costi: prezzi dei modelli e tetti di spesa ---

def _known_provider(name: str) -> None:
    if not (provider_config.exists(name) or name in registered_provider_names()):
        raise HTTPException(status_code=404, detail=f"Provider '{name}' non registrato")


@router.get("/v1/providers/costs", dependencies=AUTH)
def get_costs():
    """Prezzi, tetti e spesa del mese corrente (UTC), con quali tetti sono stati raggiunti."""
    ceilings = costs.list_ceilings()
    spend = costs.month_spend()
    total = spend.pop(costs.TOTAL_SCOPE)
    return {
        "prices": costs.list_prices(),
        "ceilings": ceilings,
        "spend": {"month": costs.month_bounds()[0].strftime("%Y-%m"), "by_provider": spend, "total": total},
        "reached": costs.reached_scopes(ceilings, {**spend, costs.TOTAL_SCOPE: total}),
    }


@router.put("/v1/providers/ceilings/{scope}", dependencies=AUTH)
def set_spend_ceiling(scope: str, req: SpendCeilingRequest):
    """Imposta il tetto mensile in dollari di un provider o del totale (`total`)."""
    if scope != costs.TOTAL_SCOPE:
        _known_provider(scope)
    return {"scope": scope, "monthly_usd": costs.set_ceiling(scope, req.monthly_usd)}


@router.delete("/v1/providers/ceilings/{scope}", dependencies=AUTH)
def delete_spend_ceiling(scope: str):
    """Toglie il tetto: nessun tetto vuol dire nessun limite."""
    if scope != costs.TOTAL_SCOPE:
        _known_provider(scope)
    return {"scope": scope, "deleted": costs.delete_ceiling(scope)}


# --- Un provider -------------------------------------------------------------------------------------

@router.get("/v1/providers/{name}", dependencies=AUTH)
def get_provider_config(name: str):
    return _call(provider_config.provider_view, name)


@router.patch("/v1/providers/{name}", dependencies=AUTH)
def patch_provider(name: str, req: PatchProviderRequest):
    """Modifica campi e credenziali; `null` riporta un campo al `.env` (o al valore di base)."""
    given = req.model_fields_set
    return _call(provider_config.patch, name, kind=req.kind,
                 display_name=req.display_name if "display_name" in given else ...,
                 enabled=req.enabled if "enabled" in given else ...,
                 fields=req.fields, secrets=req.secrets, confirm=req.confirm)


@router.delete("/v1/providers/{name}", dependencies=AUTH)
def delete_provider(name: str):
    """Elimina un provider della UI con i suoi prezzi e il suo tetto; 409 per uno del `.env` o per il ripiego."""
    _call(provider_config.delete, name)
    return {"name": name, "deleted": True}


@router.post("/v1/providers/{name}/reset", dependencies=AUTH)
def reset_provider(name: str):
    """Provider del `.env`: toglie tutte le modifiche della UI."""
    return _call(provider_config.reset, name)


@router.put("/v1/providers/{name}/clearance", dependencies=AUTH)
def set_provider_clearance(name: str, req: ClearanceRequest):
    """`{level, confirm}`: alzare il livello senza `confirm` risponde 409 `confirm_required`."""
    return _call(provider_config.set_clearance, name, req.level, req.confirm)


@router.post("/v1/providers/{name}/test", dependencies=AUTH)
def test_provider(name: str, req: Optional[PatchProviderRequest] = None):
    """Prova la connessione con la configurazione salvata o con quella inviata (senza salvarla)."""
    overrides = {"fields": req.fields, "secrets": req.secrets} if req else None
    return _call(provider_config.test_connection, name, overrides)


@router.get("/v1/providers/{name}/models", response_model=ProviderModelsResponse, dependencies=AUTH)
def get_provider_models(name: str):
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


@router.post("/v1/providers/{name}/models/load", dependencies=AUTH)
def load_provider_model_endpoint(name: str, req: LoadModelRequest):
    """Carica un modello in VRAM per il provider specificato."""
    try:
        res = load_provider_model(name, req.model)
        return {"status": "ok", "provider": name, "model": req.model, "result": res}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante il caricamento del modello '{req.model}': {e}") from e


@router.put("/v1/providers/{name}/models/{model:path}/price", dependencies=AUTH)
def set_model_price(name: str, model: str, req: ModelPriceRequest):
    """Imposta il prezzo di un modello (dollari per milione di token). L'id può contenere `/`, `:` e `.`."""
    _known_provider(name)
    return costs.set_price(name, model, req.input_per_mtok, req.cached_per_mtok, req.output_per_mtok)


@router.delete("/v1/providers/{name}/models/{model:path}/price", dependencies=AUTH)
def delete_model_price(name: str, model: str):
    """Toglie il prezzo: il modello torna a costare zero."""
    _known_provider(name)
    return {"provider": name, "model": model, "deleted": costs.delete_price(name, model)}


# --- Catalogo per il selettore dei modelli ---

@router.get("/v1/models", dependencies=AUTH)
def get_models_catalog():
    """I provider attivi, ognuno con i suoi modelli (con i dettagli di ModelDetail), e la scelta predefinita."""
    catalog = provider_config.catalog()
    for entry in catalog["providers"]:
        entry["models"] = [ModelDetail(**m).model_dump() for m in entry["models"] if m.get("id")]
    return catalog


@router.get("/v1/models/events")
async def models_events_endpoint(provider: str = "llamacpp"):
    """Cambi di stato dei modelli in tempo reale, ricavati dagli eventi di llama-swap (/api/events)."""
    import httpx
    try:
        target = providers.get_provider(provider)
    except providers.ProviderUnavailableError:
        target = None
    url = (f"{server_root(target.base_url)}/api/events"
           if isinstance(target, OpenAICompatProvider) and target.llama_cpp else None)

    async def sse_stream():
        if url is None:
            return
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
