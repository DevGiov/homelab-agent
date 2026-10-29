"""Entità dei fatti: definizioni condivise con il consolidamento della memoria e assegnazione delle entità ai fatti
che non ne hanno (`tag_untagged_facts`, a gruppi, su richiesta dall'explorer della memoria).

I fatti nascono dal consolidamento dei messaggi (`app.agent.memory_consolidation`), non più a fine turno.
"""
import logging
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from app.agent import llm_calls
from app.llm.providers import LLMUnavailableError
from app.memory import facts

logger = logging.getLogger("fact_extraction")

EntityType = Literal["person", "organization", "place", "project", "software", "infrastructure", "other"]
TAG_BATCH_SIZE = 10

ENTITY_GUIDE = (
    "Entities are the specific named things a fact is about: people, organizations, places, projects, software "
    "or services (e.g. 'Debian', 'Letta', 'Immich'), infrastructure (hosts, containers like 'CT 125', IP addresses, "
    "devices). Use the canonical name as written in the fact, without articles. Do not list generic concepts, "
    "dates or actions. Types: person, organization, place, project, software, infrastructure, other."
)


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType


class TaggedFact(BaseModel):
    id: int
    entities: List[ExtractedEntity]


class EntityTagging(BaseModel):
    facts: List[TaggedFact]


def entity_refs(items: List[ExtractedEntity]) -> List[Dict[str, str]]:
    return [{"name": e.name, "type": e.type} for e in items if e.name.strip()]


def tag_untagged_facts(limit: int = 100, model: Optional[str] = None) -> Dict[str, int]:
    """Assegna le entità ai fatti che non ne hanno, una chiamata ogni `TAG_BATCH_SIZE` fatti."""
    pending = facts.facts_without_entities(limit)
    tagged = 0
    for start in range(0, len(pending), TAG_BATCH_SIZE):
        batch = pending[start:start + TAG_BATCH_SIZE]
        listing = "\n".join(f"[{f['id']}] {f['content']}" for f in batch)
        prompt = f"""For each fact below, list the entities it mentions (empty list if none).
{ENTITY_GUIDE}
Answer with one item per fact, using the id in brackets.

{listing}"""
        try:
            result = llm_calls.call_llm_structured(
                prompt,
                "You tag the entities mentioned in facts of an assistant's long-term memory.",
                EntityTagging,
                max_tokens=2048,
                max_retries=1,
                reasoning_budget=0,
                model=model,
                reasoning_phase=None,
            )
        except LLMUnavailableError as e:
            logger.warning(f"Assegnazione entità interrotta, LLM non disponibile: {e}")
            break
        if result is None:
            continue
        found = {item.id: entity_refs(item.entities) for item in result.facts}
        # Anche i fatti senza entità vengono segnati come analizzati; quelli omessi dal modello restano in coda
        for fact in batch:
            if fact["id"] in found:
                facts.tag_fact(fact["id"], found[fact["id"]])
                tagged += bool(found[fact["id"]])
    return {"processed": len(pending), "tagged": tagged, "remaining": facts.stats()["facts_without_entities"]}
