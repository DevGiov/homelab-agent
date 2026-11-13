import base64
import logging
import os
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import image_utils
from app.core.config import settings
from app.llm import providers
from app.llm.reasoning import resolve
from app.registry.base import BaseToolRegistry
from app.security import network

logger = logging.getLogger("vision_registry")

MAX_IMAGE_BYTES = 20 * 1024 * 1024
UPLOADS_URL_PREFIX = "/v1/uploads/"


def _local_image_path(raw: str) -> Optional[Path]:
    """Il file indicato, solo se sta nella directory dei dati (upload, artefatti); None altrimenti.

    Accetta anche l'indirizzo con cui il frontend mostra un upload (`/v1/uploads/<nome>`)."""
    if raw.startswith(UPLOADS_URL_PREFIX):
        candidate = Path(settings.uploads_dir) / Path(raw[len(UPLOADS_URL_PREFIX):]).name
    else:
        candidate = Path(os.path.expanduser(raw))
        if not candidate.is_absolute():
            candidate = Path(settings.uploads_dir) / candidate
    root = Path(settings.data_dir).resolve()
    resolved = candidate.resolve()
    return resolved if resolved.is_relative_to(root) else None


class VisionRegistry(BaseToolRegistry):
    """
    Registry per tool di analisi ed ispezione visiva on-demand.
    Consente all'agente di analizzare file immagine locali o immagini da URL web.
    """

    @property
    def name(self) -> str:
        return "vision"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "inspect_image",
                "description": (
                    "Ispeziona e analizza visivamente un'immagine locale (file path sul filesystem) "
                    "oppure remota (URL web http/https). Utilizza il modello multimodale Vision per estrarre "
                    "dettagli, diagrammi, testo (OCR), grafici o verificare lo stato di elementi visivi."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_path_or_url": {
                            "type": "string",
                            "description": "Percorso assoluto del file immagine locale o URL web http/https dell'immagine da ispezionare."
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Domanda specifica o istruzione di analisi per il modello Vision (es. 'Qual è il valore sull'asse Y del picco?', 'Trascrivi il testo della ricevuta').",
                            "default": "Analizza dettagliatamente l'immagine fornita e descrivi ogni elemento rilevante, testo, dati o grafici presenti."
                        }
                    },
                    "required": ["image_path_or_url"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name != "inspect_image":
            return {"error": f"Tool '{tool_name}' non supportato dal registry Vision"}

        image_path_or_url = str(args.get("image_path_or_url", "")).strip()
        prompt = args.get("prompt") or "Analizza dettagliatamente l'immagine fornita e descrivi ogni elemento rilevante, testo, dati o grafici presenti."

        if not image_path_or_url:
            return {"error": "Il parametro 'image_path_or_url' è obbligatorio."}

        if image_path_or_url.startswith(("http://", "https://")):
            try:
                # Può sollevare ApprovalRequired: la gestisce il ToolRegistryManager
                network.require_approval_unless_listed("inspect_image", image_path_or_url)
                res = network.fetch(image_path_or_url, timeout=15.0, max_bytes=MAX_IMAGE_BYTES)
            except network.NetworkBlocked as e:
                return {"error": str(e), "blocked": True}
            except (urllib.error.URLError, OSError, ValueError) as e:
                return {"error": f"Download dell'immagine da '{image_path_or_url}' non riuscito: {e}"}
            if res.status != 200:
                return {"error": f"Errore HTTP {res.status} durante il download dell'immagine da '{image_path_or_url}'"}
            raw_bytes, source_desc = res.body, res.final_url
        else:
            local_path = _local_image_path(image_path_or_url)
            if local_path is None:
                return {"error": f"Percorso non ammesso: '{image_path_or_url}'. Si possono ispezionare solo le immagini caricate "
                                 "e gli artefatti dell'agente."}
            if not local_path.is_file():
                return {"error": f"File immagine locale non trovato: '{image_path_or_url}'"}
            raw_bytes, source_desc = local_path.read_bytes(), str(local_path)

        if not raw_bytes:
            return {"error": "Il contenuto dell'immagine è vuoto."}

        try:
            # Ottimizza e transcodifica forzando JPEG per garantire compatibilità con llama.cpp / stb_image
            opt_bytes, _mime, w, h = image_utils.optimize_image_bytes(raw_bytes, max_dimension=1920, quality=85, force_jpeg=True)
        except Exception as e:
            return {"error": f"Il file non è un'immagine leggibile: {e}"}
        data_url = f"data:image/jpeg;base64,{base64.b64encode(opt_bytes).decode('utf-8')}"

        provider = providers.get_provider()
        model = provider.effective_model(args.get("model"))
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}]
        logger.info(f"Ispezione visiva di {source_desc} ({w}x{h}, {len(opt_bytes)} byte) con '{model}'")
        reasoning = resolve(model, "medium", temperature=0.2)
        # Come call_llm: il server conta nei max_tokens anche il ragionamento
        result = provider.chat(messages, model=model, max_tokens=4096 + (reasoning.budget if reasoning.enabled else 0),
                               reasoning=reasoning)
        if result.get("error"):
            return {"error": f"Errore dal modello multimodale: {result['error']}"}

        return {
            "success": True,
            "image_source": source_desc,
            "dimensions": f"{w}x{h}",
            "analysis": (result.get("content") or "").strip(),
        }
