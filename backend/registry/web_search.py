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
            },
            {
                "name": "http_get",
                "description": (
                    "Effettua una richiesta HTTP GET verso un URL specifico (es. feed arXiv, endpoint API REST, webhook o pagina web) "
                    "e restituisce il contenuto decodificato (JSON strutturato o testo/XML)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "L'URL completo da richiedere (es. https://export.arxiv.org/api/query?...)"
                        },
                        "headers": {
                            "type": "object",
                            "description": "Dizionario facoltativo di intestazioni HTTP personalizzate"
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Timeout massimo in secondi (default 15)",
                            "default": 15
                        }
                    },
                    "required": ["url"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "http_get":
            url = str(args.get("url", "")).strip()
            if not url:
                return {"error": "Parametro 'url' mancante per 'http_get'."}
            timeout_sec = float(args.get("timeout_seconds", 15))
            custom_headers = args.get("headers") or {}

            import urllib.request
            import urllib.error
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "homelab-agent/1.0 (Automations Runner)")
            for hk, hv in custom_headers.items():
                req.add_header(str(hk), str(hv))

            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    status_code = resp.status
                    content_type = resp.headers.get("Content-Type", "")
                    raw_bytes = resp.read(1024 * 1024)  # Limite di sicurezza 1MB
                    text = raw_bytes.decode("utf-8", errors="replace")

                    if "application/json" in content_type:
                        try:
                            parsed_json = json.loads(text)
                            return {"status": status_code, "data": parsed_json, "url": url}
                        except Exception:
                            pass
                    return {"status": status_code, "content": text, "url": url}
            except urllib.error.HTTPError as e:
                return {"error": f"Errore HTTP {e.code}: {e.reason}", "status": e.code, "url": url}
            except Exception as e:
                return {"error": f"Errore richiesta HTTP a {url}: {str(e)}", "url": url}

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
