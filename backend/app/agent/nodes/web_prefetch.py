import logging
import re
from typing import Any, Dict, List, Optional

from app.agent import llm_calls
from app.agent import mode_router as router
from app.agent.state import AgentState

logger = logging.getLogger("graph")


def is_purely_visual_request(task: str) -> bool:
    """Rileva se una richiesta con immagini è puramente percettiva/descrittiva senza intento di ricerca esterna."""
    if not task or not task.strip():
        return True
    task_lower = task.lower().strip()

    # Se ci sono parole chiave che richiedono informazioni esterne, prezzi o dati attuali
    external_keywords = [
        "cerca", "search", "trova", "prezzo", "prezzi", "costo", "costi", "quanto costa",
        "dove comprare", "comprare", "acquistare", "vendita", "negozi", "store",
        "notizie", "news", "recensioni", "review", "scheda tecnica", "specifiche",
        "manuale", "firmware", "driver", "pinout", "compatibile", "compatibilità",
        "disponibilità", "mercato", "aggiornamenti", "online", "internet", "web", "google"
    ]
    if any(kw in task_lower for kw in external_keywords):
        return False

    # Se invece chiede solo di descrivere o guardare l'immagine
    visual_keywords = [
        "cosa vedi", "descrivi", "cosa c'è", "spiega l'immagine", "guarda questa",
        "analizza l'immagine", "analizza e descrivi", "cosa rappresenta", "leggi il testo",
        "trascrivi", "chi c'è", "che colore", "dov'è"
    ]
    return any(kw in task_lower for kw in visual_keywords)


def formulate_visual_search_query(task: str, images: List[str], model: Optional[str] = None) -> str:
    """
    Executes a fast and silent vision micro-pass (without SSE streaming) to extract
    the subject (brand, model, code, component) from the image and formulate a concise search query.
    """
    prompt = (
        "You are an assistant for formulating effective web search queries.\n"
        f"The user provided an image with this request: '{task}'.\n"
        "Analyze the image and accurately identify the primary subject or product (brand, model, product code, or component).\n"
        "Combine the identified subject with user intent into a concise and effective Google/SearXNG search query (maximum 4-7 words).\n"
        "Examples of expected output:\n"
        "- Eachine EV800DM price specs\n"
        "- Apple iMac G4 technical specifications\n"
        "- Raspberry Pi 4 GPIO pinout\n"
        "- Arduino Uno R3 CH340 driver\n"
        "Reply EXCLUSIVELY with the search query, without quotes, explanations, markdown formatting, or preamble."
    )
    try:
        res = llm_calls.call_llm(
            prompt=prompt,
            max_tokens=80,
            temperature=0.0,
            reasoning_budget=0,
            model=model,
            stream_mode="none",
            images=images
        )
        raw_content = res.get("content", "") if isinstance(res, dict) else (res or "")
        clean_q = re.sub(r'["\'`\n]', ' ', raw_content).strip()
        clean_q = re.sub(r'^(?:query|ricerca|cerca|search)[:\s]+', '', clean_q, flags=re.IGNORECASE).strip()
        clean_q = re.sub(r'\s+', ' ', clean_q)
        if clean_q and len(clean_q) >= 3:
            logger.info(f"Visual query grounding formulated successfully: '{clean_q}' (from task: '{task}')")
            return clean_q
    except Exception as e:
        logger.warning(f"Visual query grounding failed (fallback to original task): {e}")
    return task


def should_prefetch_web(
    task: str,
    images: Optional[List[str]] = None,
    conversation_context: Optional[str] = None,
    model: Optional[str] = None,
) -> bool:
    """
    Determines whether deterministic web prefetch should run in 'auto' mode.
    Uses the unified, dynamic model-driven router.
    """
    if not task or not task.strip():
        return False

    has_images = bool(images and len(images) > 0)
    decision = router.route_turn(
        user_input=task,
        conversation_context=conversation_context,
        has_images=has_images,
        model=model,
    )
    return decision.web_search_needed


def web_prefetch_node(state: AgentState) -> AgentState:
    """Performs deterministic read-only web prefetch before subgraphs according to web_search mode and model router decision."""
    web_search_val = state.get("web_search")
    task = state.get("task", "")
    if not task:
        return state

    images = state.get("images")
    route_decision = state.get("route_decision") or {}

    # Mode evaluation: 'off' | False -> skip
    if web_search_val is False or web_search_val == "off":
        logger.info(f"Web prefetch [OFF]: skipped for '{task}'")
        return state

    # Mode evaluation: 'on' | True -> always prefetch (unless purely visual)
    elif web_search_val is True or web_search_val == "on":
        if images and len(images) > 0 and is_purely_visual_request(task):
            logger.info(f"Purely visual request: skipping web prefetch [ON] for '{task}'")
            return state
        effective_query = route_decision.get("web_search_query") or task
        logger.info(f"Web prefetch [ON]: activated for query '{effective_query}'")

    # Mode evaluation: 'auto' (default) -> smart classification from model router
    else:
        if "web_search_needed" in route_decision:
            should_run = route_decision.get("web_search_needed", False)
        else:
            should_run = should_prefetch_web(
                task,
                images=images,
                conversation_context=state.get("memory_context"),
                model=state.get("model")
            )

        if not should_run:
            logger.info(f"Web prefetch [AUTO]: skipped for query '{task}' (decision: {route_decision.get('reasoning')})")
            return state

        effective_query = route_decision.get("web_search_query") or task
        logger.info(f"Web prefetch [AUTO]: activated for query '{effective_query}' (task: '{task}')")

    # If images are present and no search query was formulated, ground query with vision
    if images and len(images) > 0 and (not route_decision.get("web_search_query")):
        effective_query = formulate_visual_search_query(task, images, model=state.get("model"))

    q = llm_calls.stream_queue.get()

    def emit_event(ev_name: str, data: Dict[str, Any]):
        if q:
            q.put({"type": "retrieval", "event": ev_name, "data": data})

    emit_event("web_prefetch.started", {"query": effective_query})
    logger.info(f"Avvio web prefetch per query: '{effective_query}' (task originale: '{task}')")

    try:
        from app.registry.web_search_service import execute_search
        search_res = execute_search(
            query=effective_query,
            count=8,
            event_callback=emit_event
        )

        clean_sources = [
            {
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "snippet": s.get("snippet", "")
            }
            for s in search_res.get("sources", [])
        ]

        query_effective = search_res.get("query") or effective_query
        provider = search_res.get("provider_used", "Web")
        latency_ms = search_res.get("latency_ms", 0)

        # Metadati pubblici: compatti, sicuri per API, SSE e memorizzazione SQLite
        public_meta = {
            "query": query_effective,
            "success": bool(search_res.get("success")),
            "provider_used": provider,
            "latency_ms": latency_ms,
            "sources": clean_sources,
            "error": search_res.get("error")
        }

        # Contesto interno per i prompt: contiene summary_text senza strutture pesanti
        internal_data = {
            "query": query_effective,
            "success": bool(search_res.get("success")),
            "sources": clean_sources,
            "summary_text": search_res.get("summary_text", ""),
            "error": search_res.get("error")
        }

        if search_res.get("success") and clean_sources:
            emit_event("web_prefetch.completed", {
                "query": query_effective,
                "sources_count": len(clean_sources),
                "provider": provider,
                "latency_ms": latency_ms
            })
        else:
            emit_event("web_prefetch.empty", {
                "query": query_effective,
                "provider": provider
            })

        return {
            "web_prefetch_data": internal_data,
            "web_prefetch_metadata": public_meta
        }
    except Exception as e:
        logger.warning(f"Web prefetch non riuscito (non bloccante): {e}", exc_info=True)
        public_err_msg = "Ricerca web non disponibile al momento."
        emit_event("web_prefetch.failed", {"query": effective_query, "error": public_err_msg, "code": "search_unavailable"})
        public_meta = {
            "query": effective_query,
            "success": False,
            "provider_used": "Web",
            "latency_ms": 0,
            "sources": [],
            "error": "search_unavailable"
        }
        internal_data = {
            "query": effective_query,
            "success": False,
            "sources": [],
            "summary_text": "",
            "error": "search_unavailable"
        }
        return {
            "web_prefetch_data": internal_data,
            "web_prefetch_metadata": public_meta
        }
