import logging
from typing import Any, Dict, List

import guardrails
from registry.base import BaseToolRegistry
from registry.firecracker_sandbox import FirecrackerSandbox

logger = logging.getLogger("code_exec_registry")

class CodeExecRegistry(BaseToolRegistry):
    def __init__(self):
        self._sandbox = FirecrackerSandbox()

    @property
    def name(self) -> str:
        return "code"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "python_interpreter",
                "description": "Esegue uno script o snippet Python in una sandbox sicura (Firecracker microVM). Restituisce l'output dello script.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Il codice Python da eseguire (es. print(2+2))."
                        }
                    },
                    "required": ["code"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name != "python_interpreter":
            return {"error": f"Tool '{tool_name}' non gestito dal registry code."}

        code = args.get("code", "")
        if not code:
            return {"error": "Parametro 'code' mancante."}

        logger.info(f"Esecuzione codice Python in sandbox Firecracker:\n{code}")
        res = self._sandbox.execute_code(code, timeout=5)
        if not res.get("sandbox_unavailable"):
            return res

        # Sandbox non utilizzabile: l'esecuzione nel container backend (accesso a /data, .env, rete)
        # avviene solo con un'approvazione esplicita per questa capability
        if not guardrails.is_capability_approved(guardrails.LOCAL_CODE_FALLBACK):
            raise guardrails.ApprovalRequired(
                guardrails.LOCAL_CODE_FALLBACK,
                f"Sandbox Firecracker non disponibile ({res.get('error')}): il codice verrebbe eseguito "
                f"senza isolamento nel container del backend",
                preview=code,
            )
        logger.warning("Esecuzione codice Python NON isolata nel container backend (approvata dall'utente)")
        return self._sandbox.execute_local(code, timeout=5)
