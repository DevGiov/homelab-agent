"""AutomationContext per il runtime Python SDK (Milestone M5).

Consente al codice dello step di interagire in modo sicuro con il workflow:
- Accesso agli input dello step
- Lettura degli output degli step precedenti
- Recupero scoped dei secret dichiarati nella whitelist
- Creazione sicura di artefatti
- Logging strutturato
"""

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("sdk.context")


class StepResult:
    """Risultato strutturato restituito da uno step Python SDK."""

    def __init__(self, output: Any = None, success: bool = True, error: Optional[str] = None):
        self.output = output
        self.success = success
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }


class AutomationContext:
    """Contesto di runtime per gli step in codice custom Python.

    Fornisce accesso controllato alle variabili, ai secret autorizzati
    e alla memorizzazione degli artefatti generati dalla run.
    """

    def __init__(
        self,
        automation_id: str,
        run_id: str,
        step_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        step_outputs: Optional[Dict[str, Any]] = None,
        secrets: Optional[Dict[str, str]] = None,
        secrets_whitelist: Optional[List[str]] = None,
        artifacts_dir: Optional[str] = None,
    ):
        self.automation_id = automation_id
        self.run_id = run_id
        self.step_id = step_id
        self.inputs = inputs or {}
        self.step_outputs = step_outputs or {}
        self._secrets = secrets or {}
        self._secrets_whitelist = set(secrets_whitelist or [])
        self.artifacts_dir = artifacts_dir or f"/data/artifacts/{run_id}"
        self.logs: List[Dict[str, Any]] = []
        self.created_artifacts: List[Dict[str, Any]] = []

    def get_input(self, key: str, default: Any = None) -> Any:
        """Restituisce un parametro o input fornito allo step o al workflow."""
        return self.inputs.get(key, default)

    def get_step_output(self, previous_step_id: str) -> Any:
        """Recupera l'output prodotto da uno step precedente nel workflow."""
        step_data = self.step_outputs.get(previous_step_id)
        if isinstance(step_data, dict) and "output" in step_data:
            return step_data["output"]
        return step_data

    def get_secret(self, secret_name: str) -> str:
        """Recupera un secret configurato, verificando che sia nella whitelist dichiarata.

        Solleva PermissionError se il secret non è stato preventivamente autorizzato nel manifest.
        """
        if secret_name not in self._secrets_whitelist:
            raise PermissionError(
                f"Accesso al secret '{secret_name}' negato: non presente nella secrets_whitelist del manifest/policy."
            )
        val = self._secrets.get(secret_name)
        if val is None:
            # Cerca tra le variabili d'ambiente solo per i secret approvati in whitelist
            val = os.environ.get(secret_name)
        if val is None:
            raise KeyError(f"Secret '{secret_name}' non trovato tra i secret configurati.")
        return val

    def log(self, message: str, level: str = "info"):
        """Registra un messaggio di log strutturato nel contesto della run."""
        entry = {"level": level.lower(), "message": message}
        self.logs.append(entry)
        if level.lower() == "error":
            logger.error(f"[{self.automation_id}][{self.step_id}] {message}")
        elif level.lower() == "warning":
            logger.warning(f"[{self.automation_id}][{self.step_id}] {message}")
        else:
            logger.info(f"[{self.automation_id}][{self.step_id}] {message}")

    def create_artifact(
        self,
        name: str,
        content: Union[str, bytes],
        artifact_type: str = "report",
        mime_type: str = "text/plain",
    ) -> Dict[str, Any]:
        """Salva un artefatto su filesystem protetto e ne registra i metadati con checksum."""
        os.makedirs(self.artifacts_dir, exist_ok=True)
        safe_name = os.path.basename(name)
        file_path = os.path.join(self.artifacts_dir, safe_name)

        if isinstance(content, str):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            raw_bytes = content.encode("utf-8")
        else:
            with open(file_path, "wb") as f:
                f.write(content)
            raw_bytes = content

        checksum = hashlib.sha256(raw_bytes).hexdigest()
        artifact_meta = {
            "name": safe_name,
            "type": artifact_type,
            "mime_type": mime_type,
            "storage_uri": file_path,
            "checksum_sha256": checksum,
        }
        self.created_artifacts.append(artifact_meta)
        return artifact_meta
