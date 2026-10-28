"""Estrazione dei fatti da ricordare, con le entità che citano, in un'unica chiamata a output vincolato.

`remember_turn` gira a fine turno (non in incognito); `tag_untagged_facts` assegna le entità ai fatti salvati
prima che esistessero, a gruppi, su richiesta dall'explorer della memoria.
"""
import logging
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agent import llm_calls
from app.llm.providers import LLMUnavailableError
from app.memory import facts

logger = logging.getLogger("fact_extraction")

EntityType = Literal["person", "organization", "place", "project", "software", "infrastructure", "other"]
MAX_FACTS_PER_TURN = 5
TAG_BATCH_SIZE = 10

_ENTITY_GUIDE = (
    "Entities are the specific named things a fact is about: people, organizations, places, projects, software "
    "or services (e.g. 'Debian', 'Letta', 'Immich'), infrastructure (hosts, containers like 'CT 125', IP addresses, "
    "devices). Use the canonical name as written in the fact, without articles. Do not list generic concepts, "
    "dates or actions. Types: person, organization, place, project, software, infrastructure, other."
)


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType


class ExtractedFact(BaseModel):
    text: str = Field(description="One self-contained fact, in the language of the conversation")
    entities: List[ExtractedEntity]


class FactExtraction(BaseModel):
    facts: List[ExtractedFact] = Field(max_length=MAX_FACTS_PER_TURN)


class TaggedFact(BaseModel):
    id: int
    entities: List[ExtractedEntity]


class EntityTagging(BaseModel):
    facts: List[TaggedFact]


def _entities(items: List[ExtractedEntity]) -> List[Dict[str, str]]:
    return [{"name": e.name, "type": e.type} for e in items if e.name.strip()]


def extract_facts(task: str, response: str, memory_context: str, model: Optional[str] = None) -> List[ExtractedFact]:
    """Fatti durevoli del turno (al massimo 5), ognuno con le sue entità; lista vuota se non c'è nulla da ricordare."""
    if not task or not response:
        return []
    prompt = f"""Extract the facts from this conversation turn that are worth remembering in future conversations:
user preferences, decisions, the state of the user's infrastructure and projects, people and their roles,
commitments and dates. Each fact must be understandable on its own, without the conversation.
Do NOT extract: the conversation itself ("the user asked...", "the assistant replied..."), general knowledge
the assistant explained, transient errors, or anything already in the existing context.
Return an empty list when nothing is worth remembering. At most {MAX_FACTS_PER_TURN} facts.
{_ENTITY_GUIDE}

User task: {task}
Assistant response: {response}
Existing context: {memory_context}"""
    try:
        result = llm_calls.call_llm_structured(
            prompt,
            "You extract durable facts and the entities they mention for an assistant's long-term memory.",
            FactExtraction,
            max_tokens=1024,
            max_retries=1,
            reasoning_budget=0,
            model=model,
            reasoning_phase=None,
        )
    except LLMUnavailableError as e:
        logger.warning(f"Estrazione fatti saltata, LLM non disponibile: {e}")
        return []
    return [f for f in (result.facts if result else []) if len(f.text.strip()) > 5][:MAX_FACTS_PER_TURN]


def remember_turn(task: str, response: str, memory_context: str, thread_id: str, model: Optional[str] = None) -> int:
    """Estrae e salva i fatti del turno; restituisce quanti sono nuovi (i quasi-duplicati ricevono solo le entità)."""
    created = 0
    for fact in extract_facts(task, response, memory_context, model=model):
        _, is_new = facts.add_fact(
            fact.text, thread_id=thread_id, entities=_entities(fact.entities), source="conversation", entities_checked=True
        )
        created += is_new
    return created


def tag_untagged_facts(limit: int = 100, model: Optional[str] = None) -> Dict[str, int]:
    """Assegna le entità ai fatti che non ne hanno, una chiamata ogni `TAG_BATCH_SIZE` fatti."""
    pending = facts.facts_without_entities(limit)
    tagged = 0
    for start in range(0, len(pending), TAG_BATCH_SIZE):
        batch = pending[start:start + TAG_BATCH_SIZE]
        listing = "\n".join(f"[{f['id']}] {f['content']}" for f in batch)
        prompt = f"""For each fact below, list the entities it mentions (empty list if none).
{_ENTITY_GUIDE}
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
        found = {item.id: _entities(item.entities) for item in result.facts}
        # Anche i fatti senza entità vengono segnati come analizzati; quelli omessi dal modello restano in coda
        for fact in batch:
            if fact["id"] in found:
                facts.tag_fact(fact["id"], found[fact["id"]])
                tagged += bool(found[fact["id"]])
    return {"processed": len(pending), "tagged": tagged, "remaining": facts.stats()["facts_without_entities"]}
