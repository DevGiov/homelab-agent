import base64
import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

import config
import image_utils
from registry.base import BaseToolRegistry

logger = logging.getLogger("vision_registry")

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

        image_path_or_url = args.get("image_path_or_url", "").strip()
        prompt = args.get("prompt") or "Analizza dettagliatamente l'immagine fornita e descrivi ogni elemento rilevante, testo, dati o grafici presenti."

        if not image_path_or_url:
            return {"error": "Il parametro 'image_path_or_url' è obbligatorio."}

        try:
            raw_bytes = None
            source_desc = image_path_or_url

            if image_path_or_url.startswith("http://") or image_path_or_url.startswith("https://"):
                logger.info(f"Download immagine remota da URL: {image_path_or_url}")
                resp = requests.get(image_path_or_url, timeout=15, headers={"User-Agent": "Homelab-Agent/1.0"})
                if resp.status_code != 200:
                    return {"error": f"Errore HTTP {resp.status_code} durante il download dell'immagine da '{image_path_or_url}'"}
                raw_bytes = resp.content
            else:
                local_path = os.path.abspath(os.path.expanduser(image_path_or_url))
                if not os.path.exists(local_path):
                    return {"error": f"File immagine locale non trovato: '{local_path}'"}
                with open(local_path, "rb") as f:
                    raw_bytes = f.read()
                source_desc = local_path

            if not raw_bytes or len(raw_bytes) == 0:
                return {"error": "Il contenuto dell'immagine è vuoto."}

            # Ottimizza e transcodifica forzando JPEG per garantire compatibilità con llama.cpp / stb_image
            opt_bytes, mime, w, h = image_utils.optimize_image_bytes(
                raw_bytes,
                max_dimension=1920,
                quality=85,
                force_jpeg=True
            )
            b64_data = base64.b64encode(opt_bytes).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{b64_data}"

            # Inoltra all'endpoint multimodale llama.cpp
            llama_url = f"{config.LLAMA_CPP_URL.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json"}
            api_key = getattr(config, "LLAMA_CPP_API_KEY", "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "model": config.DEFAULT_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}}
                        ]
                    }
                ],
                "max_tokens": 4096,
                "temperature": 0.2,
                "chat_template_kwargs": {"enable_thinking": True}
            }

            logger.info(f"Invio immagine ({w}x{h}, {len(opt_bytes)} bytes) a {llama_url} per ispezione visiva on-demand")
            llm_res = requests.post(llama_url, json=payload, headers=headers, timeout=60)
            if llm_res.status_code != 200:
                return {"error": f"Errore dall'endpoint multimodale (status {llm_res.status_code}): {llm_res.text}"}

            res_json = llm_res.json()
            choice = res_json["choices"][0]["message"]
            analysis = choice.get("content", "").strip()

            return {
                "success": True,
                "image_source": source_desc,
                "dimensions": f"{w}x{h}",
                "analysis": analysis
            }

        except Exception as e:
            logger.error(f"Errore durante l'ispezione dell'immagine '{image_path_or_url}': {e}", exc_info=True)
            return {"error": f"Eccezione durante l'analisi visiva: {str(e)}"}
