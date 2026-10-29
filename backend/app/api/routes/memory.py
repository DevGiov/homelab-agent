"""Memoria a lungo termine: profilo dell'utente, fatti, entità che citano e relazioni tra entità, episodi di esecuzione (explorer della memoria)."""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.agent.fact_extraction import tag_untagged_facts
from app.api.deps import verify_api_key
from app.memory import episodes, facts, profile

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


class ProfileInput(BaseModel):
    content: str = Field(max_length=profile.MAX_CHARS)


def _refs(entities: List[EntityRef]) -> List[Dict[str, str]]:
    return [e.model_dump() for e in entities]


@router.get("/stats")
def get_stats() -> Dict[str, int]:
    return {**facts.stats(), "episodes": episodes.list_episodes(limit=1)[1]}


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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Elenco dal più recente o, con `query`, i fatti più simili per significato (con punteggio)."""
    if query and query.strip():
        items = facts.search_facts(query.strip(), k=limit, thread_id=thread_id, entity_id=entity_id)
        return {"facts": items, "total": len(items)}
    items, total = facts.list_facts(thread_id=thread_id, entity_id=entity_id, limit=limit, offset=offset)
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
