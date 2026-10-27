from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:
    import jsonschema
except ImportError:
    jsonschema = None
import logging

logger = logging.getLogger("tool_schemas")

class ToolSelection(BaseModel):
    """Output strutturato che l'LLM deve produrre per selezionare un tool o rispondere."""
    tool_needed: bool = Field(description="True se serve chiamare un tool, False se si può rispondere direttamente o se l'azione è completata")
    tool_name: Optional[str] = Field(default=None, description="Nome esatto del tool dal catalogo, o null se tool_needed=False")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Argomenti per il tool, secondo il suo schema")
    parallel_calls: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Fase 3.3: lista di {tool_name, arguments} per chiamate read-only indipendenti da eseguire in parallelo. Usare SOLO per tool di sola lettura."
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidenza nella scelta, da 0 a 1")
    reasoning: str = Field(default="", description="Motivazione o spiegazione interna della decisione (Chain of Thought)")
    final_answer: Optional[str] = Field(default=None, description="Risposta finale formattata ed esplicita per l'utente, da compilare specialmente quando tool_needed=False")
    raw_thinking: Optional[str] = Field(default=None, description="Thinking nativo catturato durante la chiamata LLM")

def validate_tool_args(tool_name: str, arguments: dict, tools_catalog: List[dict]) -> Optional[str]:
    """Valida gli argomenti contro lo schema del tool. Ritorna None se ok, altrimenti messaggio di errore."""
    if not tool_name:
        return None
    tool_def = next((t for t in tools_catalog if t["name"] == tool_name), None)
    if not tool_def or not tool_def.get("parameters"):
        return None

    schema = tool_def["parameters"]
    if not isinstance(schema, dict) or "properties" not in schema:
        return None

    if jsonschema is None:
        # Fallback se jsonschema non è installato
        reqs = schema.get("required", [])
        for r in reqs:
            if r not in (arguments or {}):
                return f"Parametro richiesto '{r}' mancante per '{tool_name}'"
        return None

    try:
        jsonschema.validate(instance=arguments or {}, schema=schema)
        return None
    except jsonschema.ValidationError as e:
        err_msg = f"Validazione schema fallita per '{tool_name}': {e.message}"
        logger.warning(err_msg)
        return err_msg

