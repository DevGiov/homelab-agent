"""Memoria a lungo termine: profilo dell'utente, fatti, entità che citano e relazioni tra entità, episodi di esecuzione e
procedure (explorer della memoria)."""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.agent.fact_extraction import tag_untagged_facts
from app.api.deps import verify_api_key
from app.memory import episodes, facts, procedures, profile

router = APIRouter(prefix="/v1/memory", tags=["memory"], dependencies=[Depends(verify_api_key)])

EntityType = Literal["person", "organization", "place", "project", "software", "infrastructure", "other"]


class EntityRef(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: EntityType = "other"


class FactInput(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    entities: List[EntityRef] = []


class EntityUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: EntityType


class EntityMerge(BaseModel):
    into: int


class ProcedureInput(BaseModel):
    kind: Literal["tool_note", "plan_template"]
    title: str = Field(min_length=1, max_length=procedures.MAX_TITLE_CHARS)
    content: str = Field(min_length=1, max_length=procedures.MAX_CONTENT_CHARS)
    tool_name: Optional[str] = Field(default=None, max_length=200)


class ProcedureUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=procedures.MAX_TITLE_CHARS)
    content: str = Field(min_length=1, max_length=procedures.MAX_CONTENT_CHARS)
    tool_name: Optional[str] = Field(default=None, max_length=200)


class ProfileInput(BaseModel):
    content: str = Field(max_length=profile.MAX_CHARS)


def _refs(entities: List[EntityRef]) -> List[Dict[str, str]]:
    return [e.model_dump() for e in entities]


@router.get("/stats")
def get_stats() -> Dict[str, int]:
    return {**facts.stats(), "episodes": episodes.list_episodes(limit=1)[1], "procedures_proposed": procedures.counts()["proposed"]}


@router.get("/profile")
def get_profile() -> Dict[str, Any]:
    return profile.get_profile()


@router.put("/profile")
def update_profile(body: ProfileInput) -> Dict[str, Any]:
    """Note stabili sull'utente, all'inizio della memoria di ogni turno (vuoto = nessun profilo)."""
    return profile.save_profile(body.content)


@router.get("/facts")
def get_facts(
    query: Optional[str] = None,
    thread_id: Optional[str] = None,
    entity_id: Optional[int] = None,
    include_superseded: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Elenco dal più recente (con `include_superseded` anche i fatti superati) o, con `query`, i fatti validi più
    pertinenti (con punteggio)."""
    if query and query.strip():
        items = facts.search_facts(query.strip(), k=limit, thread_id=thread_id, entity_id=entity_id)
        return {"facts": items, "total": len(items)}
    items, total = facts.list_facts(thread_id=thread_id, entity_id=entity_id, include_superseded=include_superseded,
                                    limit=limit, offset=offset)
    return {"facts": items, "total": total}


@router.post("/facts", status_code=201)
def create_fact(body: FactInput) -> Dict[str, Any]:
    fact_id, created = facts.add_fact(body.content, entities=_refs(body.entities), entities_checked=bool(body.entities))
    if fact_id is None:
        raise HTTPException(status_code=400, detail="Fatto non salvato: testo vuoto o modello di embedding non disponibile.")
    if not created:
        raise HTTPException(status_code=409, detail=f"Esiste già un fatto equivalente (#{fact_id}).")
    return facts.get_fact(fact_id)


@router.put("/facts/{fact_id}")
def update_fact(fact_id: int, body: FactInput) -> Dict[str, Any]:
    fact = facts.update_fact(fact_id, body.content, _refs(body.entities))
    if fact is None:
        raise HTTPException(status_code=404, detail=f"Fatto #{fact_id} non trovato.")
    return fact


@router.post("/facts/{fact_id}/restore")
def restore_fact(fact_id: int) -> Dict[str, Any]:
    """Un fatto superato torna valido."""
    fact = facts.restore_fact(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail=f"Fatto #{fact_id} non trovato.")
    return fact


@router.delete("/facts/{fact_id}", status_code=204)
def delete_fact(fact_id: int) -> None:
    if not facts.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail=f"Fatto #{fact_id} non trovato.")


@router.delete("/facts")
def clear_facts() -> Dict[str, int]:
    """Cancella tutti i fatti e le entità; conversazioni e knowledge base restano."""
    return {"deleted": facts.clear_facts()}


@router.get("/entities")
def get_entities(query: Optional[str] = None, type: Optional[EntityType] = None) -> List[Dict[str, Any]]:
    return facts.list_entities(query=query, entity_type=type)


@router.get("/entities/{entity_id}")
def get_entity(entity_id: int) -> Dict[str, Any]:
    entity = facts.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entità #{entity_id} non trovata.")
    return entity


@router.put("/entities/{entity_id}")
def update_entity(entity_id: int, body: EntityUpdate) -> Dict[str, Any]:
    try:
        entity = facts.update_entity(entity_id, body.name, body.type)
    except facts.EntityConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entità #{entity_id} non trovata.")
    return entity


@router.post("/entities/{entity_id}/merge")
def merge_entity(entity_id: int, body: EntityMerge) -> Dict[str, Any]:
    """Unisce l'entità in `into`: i suoi fatti passano all'altra e lei viene eliminata."""
    entity = facts.merge_entities(entity_id, body.into)
    if entity is None:
        raise HTTPException(status_code=404, detail="Una delle due entità non esiste.")
    return entity


@router.delete("/entities/{entity_id}", status_code=204)
def delete_entity(entity_id: int) -> None:
    if not facts.delete_entity(entity_id):
        raise HTTPException(status_code=404, detail=f"Entità #{entity_id} non trovata.")


@router.post("/entities/extract")
def extract_entities(limit: int = Query(100, ge=1, le=500)) -> Dict[str, int]:
    """Assegna con l'LLM le entità ai fatti mai analizzati (per esempio quelli salvati prima delle entità)."""
    return tag_untagged_facts(limit)


@router.get("/episodes")
def get_episodes(
    query: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Episodi di esecuzione dal più recente o, con `query`, i più pertinenti (con punteggio)."""
    if query and query.strip():
        items = episodes.search_episodes(query.strip(), k=limit, min_score=facts.RELEVANT_SCORE)
        return {"episodes": items, "total": len(items)}
    items, total = episodes.list_episodes(limit=limit, offset=offset)
    return {"episodes": items, "total": total}


@router.delete("/episodes/{episode_id}", status_code=204)
def delete_episode(episode_id: int) -> None:
    if not episodes.delete_episode(episode_id):
        raise HTTPException(status_code=404, detail=f"Episodio #{episode_id} non trovato.")


@router.delete("/episodes")
def clear_episodes() -> Dict[str, int]:
    """Cancella tutti gli episodi di esecuzione; fatti e conversazioni restano."""
    return {"deleted": episodes.clear_episodes()}


def _procedure_or_404(procedure: Optional[Dict[str, Any]], procedure_id: int) -> Dict[str, Any]:
    if procedure is None:
        raise HTTPException(status_code=404, detail=f"Procedura #{procedure_id} non trovata.")
    return procedure


@router.get("/procedures")
def get_procedures(
    status: Optional[Literal["proposed", "approved", "rejected"]] = None,
    kind: Optional[Literal["tool_note", "plan_template"]] = None,
) -> List[Dict[str, Any]]:
    """Proposte in attesa prima, poi approvate e rifiutate."""
    return procedures.list_procedures(status=status, kind=kind)


@router.get("/procedures/tools")
def get_procedure_tools() -> List[str]:
    """Nomi dei tool a cui una nota può riferirsi: il catalogo di act."""
    from app.agent.mode_policy import get_mode_policy
    from app.registry.manager import get_registry_manager

    return sorted(t["name"] for t in get_registry_manager().get_tools_for_mode(get_mode_policy("act").allowed_registries))


@router.post("/procedures", status_code=201)
def create_procedure(body: ProcedureInput) -> Dict[str, Any]:
    """Procedura scritta dall'utente: è subito in uso."""
    try:
        return procedures.create(body.kind, body.title, body.content, tool_name=body.tool_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/procedures/{procedure_id}")
def update_procedure(procedure_id: int, body: ProcedureUpdate) -> Dict[str, Any]:
    try:
        return _procedure_or_404(procedures.update(procedure_id, body.title, body.content, body.tool_name), procedure_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/procedures/{procedure_id}/approve")
def approve_procedure(procedure_id: int) -> Dict[str, Any]:
    return _procedure_or_404(procedures.approve(procedure_id), procedure_id)


@router.post("/procedures/{procedure_id}/reject")
def reject_procedure(procedure_id: int) -> Dict[str, Any]:
    """Esce dall'uso e resta come rifiutata, così la stessa proposta non torna."""
    return _procedure_or_404(procedures.reject(procedure_id), procedure_id)


@router.delete("/procedures/{procedure_id}", status_code=204)
def delete_procedure(procedure_id: int) -> None:
    if not procedures.delete(procedure_id):
        raise HTTPException(status_code=404, detail=f"Procedura #{procedure_id} non trovata.")


@router.get("/consolidation")
def get_consolidation() -> Dict[str, Any]:
    """Stato del consolidamento: in corso, ultima esecuzione con l'esito, messaggi ancora da consolidare."""
    from app.agent import memory_consolidation

    return memory_consolidation.status()


@router.post("/consolidation", status_code=202)
def start_consolidation() -> Dict[str, Any]:
    """Consolida subito i messaggi nuovi e deduplica i fatti, in background, con il modello attivo."""
    from app.agent import memory_consolidation

    if not memory_consolidation.run_in_background():
        raise HTTPException(status_code=409, detail="Consolidamento già in corso.")
    return {"started": True}
