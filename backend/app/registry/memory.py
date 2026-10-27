"""Registry 'memory': recall dalla memoria archivistica Letta (Fase 2.2).

Espone la ricerca ibrida (BM25 + dense + RRF) sulla memoria archivistica
di Letta come tool richiamabile dall'agente.
"""
import logging
from typing import Any, Dict, List

from app.memory import letta_client
from app.registry.base import BaseToolRegistry

logger = logging.getLogger("memory_registry")


class MemoryRegistry(BaseToolRegistry):
    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "memory"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "recall_memory",
                "description": (
                    "Cerca nella memoria a lungo termine dell'agente (conversazioni e fatti passati). "
                    "Usalo quando l'utente fa riferimento a interazioni, decisioni o preferenze precedenti."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Cosa cercare nella memoria (es. 'preferenze container', 'IP allocati la scorsa volta')."
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "ID del thread di cui cercare la memoria (opzionale)."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "knowledge_search",
                "description": (
                    "Cerca nei documenti della knowledge base (file .md, .txt, .pdf caricati dall'utente: "
                    "documentazione homelab, guide, note tecniche). Usa quando la risposta potrebbe trovarsi nei documenti."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Cosa cercare nei documenti (es. 'configurazione nginx', 'procedura backup')."
                        },
                        "k": {
                            "type": "integer",
                            "description": "Numero massimo di risultati (default 5)."
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "knowledge_search":
            return self._knowledge_search(args)
        if tool_name != "recall_memory":
            return {"error": f"Tool '{tool_name}' non gestito dal registry memory."}

        query = args.get("query", "")
        thread_id = args.get("thread_id")
        if not query:
            return {"error": "Parametro 'query' mancante."}

        # Risolve l'agent_id dal thread_id se fornito
        agent_id = None
        if thread_id:
            agent_id = letta_client.create_thread(thread_id)
        else:
            # Ricerca su tutti gli agenti: usa il più recente come fallback
            try:
                import httpx
                headers = letta_client.HEADERS
                r = httpx.get(f"{letta_client.LETTA_URL}/v1/agents/", headers=headers, timeout=5)
                if r.status_code == 200 and isinstance(r.json(), list):
                    agents = r.json()
                    results = []
                    for ag in agents[:5]:
                        docs = letta_client.search_archival_memory_hybrid(ag["id"], query, k=5)
                        for d in docs:
                            d["agent_name"] = ag.get("name")
                        results.extend(docs)
                    return {"results": results[:10]} if results else {"results": [], "note": "Nessun risultato in memoria."}
            except Exception as e:
                logger.warning(f"Ricerca memoria globale fallita: {e}")
                return {"error": f"Memoria non raggiungibile: {e}"}

        if not agent_id:
            return {"error": "Impossibile risolvere l'agente per la ricerca memoria."}

        try:
            docs = letta_client.search_archival_memory_hybrid(agent_id, query, k=8)
            if not docs:
                return {"results": [], "note": "Nessun risultato trovato in memoria archivistica."}
            return {"results": [
                {"content": d.get("text") or d.get("content") or "", "score": d.get("score")}
                for d in docs
            ]}
        except Exception as e:
            logger.warning(f"search_archival_memory_hybrid fallito: {e}")
            return {"error": f"Ricerca memoria fallita: {e}"}

    def _knowledge_search(self, args: Dict[str, Any]) -> Any:
        """Ricerca nella knowledge base documentale (Fase 2.3)."""
        from app.memory.knowledge_base import search_knowledge
        query = args.get("query", "")
        k = int(args.get("k", 5))
        if not query:
            return {"error": "Parametro 'query' mancante."}
        results = search_knowledge(query, k=k)
        if not results:
            return {"results": [], "note": "Nessun documento rilevante in KB."}
        return {"results": results}
