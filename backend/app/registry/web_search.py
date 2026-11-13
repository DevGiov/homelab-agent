import json
import logging
import urllib.error
from typing import Any, Dict, List

from app.registry.base import BaseToolRegistry
from app.registry.web_search_service import (
    execute_search,
    search_with_fallback,
)
from app.security import network

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
                    "e restituisce il contenuto decodificato (JSON strutturato o testo/XML). Gli host fuori dalla lista degli host "
                    "ammessi richiedono la conferma dell'utente; quelli della rete locale non in lista sono bloccati."
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
            return self._http_get(args)

        if tool_name != "web_search":
            return {"error": f"Tool '{tool_name}' sconosciuto nel registry web."}

        query = args.get("query", "").strip()
        if not query:
            return {"error": "Parametro 'query' mancante."}

        logger.info(f"Agent tool web_search avviato per: {query}")
        if args.get("detail") == "full":
            # Il prefetch del grafo: vuole sorgenti, provider e latenza, non il testo per il modello
            return execute_search(query=query, count=int(args.get("count") or 8))
        search_res = execute_search(query, count=10)

        result_text = search_res.get("summary_text", "")
        sources = search_res.get("sources", [])
        if sources:
            sources_json = json.dumps(sources, ensure_ascii=False)
            result_text += f"\n\n<!-- SOURCES:{sources_json} -->"

        return {"query": query, "result": result_text}

    def _http_get(self, args: Dict[str, Any]) -> Any:
        url = str(args.get("url", "")).strip()
        if not url:
            return {"error": "Parametro 'url' mancante per 'http_get'."}
        try:
            timeout_sec = min(max(float(args.get("timeout_seconds") or 15), 1.0), 60.0)
        except (TypeError, ValueError):
            timeout_sec = 15.0
        custom_headers = args.get("headers") or {}
        if not isinstance(custom_headers, dict):
            return {"error": "Il parametro 'headers' deve essere un oggetto nome -> valore.", "url": url}

        try:
            # Può sollevare ApprovalRequired: la gestisce il ToolRegistryManager
            network.require_approval_unless_listed("http_get", url, custom_headers)
            res = network.fetch(url, headers=custom_headers, timeout=timeout_sec)
        except network.NetworkBlocked as e:
            return {"error": str(e), "blocked": True, "url": url}
        except urllib.error.URLError as e:
            return {"error": f"Errore richiesta HTTP a {url}: {e.reason}", "url": url}
        except (TimeoutError, OSError, ValueError) as e:
            return {"error": f"Errore richiesta HTTP a {url}: {e}", "url": url}

        text = res.body.decode("utf-8", errors="replace")
        base = {"status": res.status, "url": url}
        if res.final_url != url:
            base["final_url"] = res.final_url
        if res.status >= 400:
            return {**base, "error": f"Errore HTTP {res.status}", "content": text[:2000]}
        content_type = next((v for k, v in res.headers.items() if k.lower() == "content-type"), "")
        if "application/json" in content_type:
            try:
                return {**base, "data": json.loads(text)}
            except ValueError:
                pass
        return {**base, "content": text}
