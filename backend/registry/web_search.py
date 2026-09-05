import json
import logging
import os
import sys
from typing import Any, Dict, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from registry.base import BaseToolRegistry
from registry.web_search_service import (
    deduplicate_by_url,
    execute_search,
    search_with_fallback,
)

logger = logging.getLogger("web_search_registry")

# Backward compatibility alias
_search_with_fallback = search_with_fallback


class WebSearchRegistry(BaseToolRegistry):
    @property
    def name(self) -> str:
        return "web"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": (
                    "Esegue una ricerca web completa (Google, Bing, Brave, DDG tramite SearXNG e motori aggregati): "
                    "scarica il contenuto delle pagine trovate, estrae tabelle, liste e testo "
                    "restituendo un report strutturato e classificato per rilevanza. "
                    "Usa query naturali e concise senza aggiungere anni arbitrari a meno che l'utente non lo richieda esplicitamente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "La query di ricerca da inviare al motore. Deve essere concisa e naturale."
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name != "web_search":
            return {"error": f"Tool '{tool_name}' sconosciuto nel registry web."}

        query = args.get("query", "").strip()
        if not query:
            return {"error": "Parametro 'query' mancante."}

        logger.info(f"Agent tool web_search avviato per: {query}")
        search_res = execute_search(query, count=10)

        result_text = search_res.get("summary_text", "")
        sources = search_res.get("sources", [])
        if sources:
            sources_json = json.dumps(sources, ensure_ascii=False)
            result_text += f"\n\n<!-- SOURCES:{sources_json} -->"

        return {"query": query, "result": result_text}
