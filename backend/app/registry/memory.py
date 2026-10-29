"""Registry 'memory': ricerca nei fatti della memoria a lungo termine, nelle conversazioni passate e nella knowledge base."""
from typing import Any, Dict, List

from app.memory import facts, hybrid_search
from app.registry.base import BaseToolRegistry


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
                    "Cerca nei fatti della memoria a lungo termine (preferenze, decisioni, infrastruttura, persone, "
                    "progetti emersi in conversazioni passate), con le entità citate da ogni fatto. "
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
                            "description": "Limita ai fatti emersi in questo thread (opzionale)."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_conversations",
                "description": (
                    "Cerca per parole nei messaggi delle conversazioni passate (utente e agente), con un estratto e la data. "
                    "Usalo per ritrovare decisioni, configurazioni, comandi o dettagli discussi in precedenza che non sono "
                    "tra i fatti di recall_memory; cerca con i termini esatti (nomi di servizi, ID dei container, host)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Parole da cercare (es. 'nginx CT 125 certificato', 'vzdump retention')."
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Limita a una conversazione (opzionale)."
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
        if tool_name == "search_conversations":
            return self._search_conversations(args)
        if tool_name != "recall_memory":
            return {"error": f"Tool '{tool_name}' non gestito dal registry memory."}

        query = args.get("query", "")
        if not query:
            return {"error": "Parametro 'query' mancante."}
        hits = facts.search_facts(query, k=8, thread_id=args.get("thread_id"))
        if not hits:
            return {"results": [], "note": "Nessun fatto pertinente in memoria."}
        return {
            "results": [
                {
                    "fact": f["content"],
                    "entities": [e["name"] for e in f["entities"]],
                    "score": f["score"],
                    "thread_id": f["thread_id"],
                    "created_at": f["created_at"],
                }
                for f in hits
            ]
        }

    def _search_conversations(self, args: Dict[str, Any]) -> Any:
        query = args.get("query", "")
        if not query:
            return {"error": "Parametro 'query' mancante."}
        results = hybrid_search.search_messages(query, k=8, thread_id=args.get("thread_id"))
        if not results:
            return {"results": [], "note": "Nessun messaggio con queste parole nelle conversazioni passate."}
        return {"results": results}

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
