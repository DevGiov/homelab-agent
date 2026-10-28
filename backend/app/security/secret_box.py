"""Cifratura simmetrica (Fernet) dei segreti salvati a riposo: credenziali delle integrazioni e token dei server MCP.

La chiave deriva da API_SECRET_KEY: ruotarla rende illeggibili i segreti già salvati.
"""
import base64
import hashlib
import json
import logging
from typing import Any, Dict

from cryptography.fernet import Fernet

from app.core.config import settings

logger = logging.getLogger("secret_box")


def _get_fernet() -> Fernet:
    """Deriva una chiave Fernet a 32 byte univoca basata su API_SECRET_KEY."""
    raw_seed = (settings.api_secret_key.strip() or "homelab-default-integration-secret-salt").encode("utf-8")
    digest = hashlib.sha256(raw_seed).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_secrets(secrets: Dict[str, Any]) -> str:
    """Cifra un dizionario di secret in una stringa base64 Fernet."""
    if not secrets:
        return "{}"
    try:
        f = _get_fernet()
        json_bytes = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
        return f.encrypt(json_bytes).decode("utf-8")
    except Exception as e:
        logger.error(f"Errore cifratura secrets: {e}")
        return "{}"


def decrypt_secrets(encrypted_payload: str) -> Dict[str, Any]:
    """Decifra una stringa Fernet in un dizionario di secret."""
    if not encrypted_payload or encrypted_payload == "{}":
        return {}
    try:
        f = _get_fernet()
        decrypted_bytes = f.decrypt(encrypted_payload.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as e:
        logger.warning(f"Errore decifratura secrets: {e}")
        return {}
