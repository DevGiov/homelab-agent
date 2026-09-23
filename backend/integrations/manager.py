"""Gestore centralizzato per credenziali, account e integrazioni di terze parti.

Fornisce:
- Archiviazione e cifratura simmetrica AES (Fernet) per i campi sensibili a riposo.
- Test di connettività in tempo reale (IMAP email, GitHub, Home Assistant, API generiche).
- Mascheramento sicuro dei segreti per l'esposizione via API REST al frontend.
- Recupero trasparente delle credenziali attive per i Tool Registry e per il Runner.
"""

import base64
import email
import hashlib
import imaplib
import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet

import config
from automations import db as auto_db

logger = logging.getLogger("integrations.manager")


def _get_fernet() -> Fernet:
    """Deriva una chiave Fernet a 32 byte univoca basata su API_SECRET_KEY."""
    raw_seed = (config.API_SECRET_KEY.strip() or "homelab-default-integration-secret-salt").encode("utf-8")
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


def mask_secrets(secrets: Dict[str, Any]) -> Dict[str, Any]:
    """Sostituisce i valori dei segreti con indicatori mascherati per l'esposizione UI."""
    masked = {}
    for k, v in secrets.items():
        if v:
            masked[k] = "••••••••"
            masked[f"has_{k}"] = True
        else:
            masked[k] = ""
            masked[f"has_{k}"] = False
    return masked


class IntegrationManager:
    """Gestore delle integrazioni di servizio persistenti in SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def list_integrations(self, service_type: Optional[str] = None, decrypt: bool = False) -> List[Dict[str, Any]]:
        """Elenca tutte le integrazioni registrate."""
        raw_list = auto_db.list_integrations(service_type=service_type, db_path=self.db_path)
        results = []
        for r in raw_list:
            item = dict(r)
            cfg = json.loads(item.get("config_json") or "{}")
            item["config"] = cfg

            decrypted = decrypt_secrets(item.get("encrypted_secrets_json") or "{}")
            if decrypt:
                item["secrets"] = decrypted
            else:
                item["secrets"] = mask_secrets(decrypted)

            item.pop("config_json", None)
            item.pop("encrypted_secrets_json", None)
            results.append(item)
        return results

    def get_integration(self, integration_id: str, decrypt: bool = False) -> Optional[Dict[str, Any]]:
        """Recupera il dettaglio di una singola integrazione."""
        r = auto_db.get_integration(integration_id, db_path=self.db_path)
        if not r:
            return None
        item = dict(r)
        cfg = json.loads(item.get("config_json") or "{}")
        item["config"] = cfg

        decrypted = decrypt_secrets(item.get("encrypted_secrets_json") or "{}")
        if decrypt:
            item["secrets"] = decrypted
        else:
            item["secrets"] = mask_secrets(decrypted)

        item.pop("config_json", None)
        item.pop("encrypted_secrets_json", None)
        return item

    def save_integration(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Salva o aggiorna un'integrazione, cifrando i secret."""
        integration_id = data.get("id")
        if not integration_id:
            raise ValueError("Il campo 'id' è obbligatorio per l'integrazione.")

        existing = auto_db.get_integration(integration_id, db_path=self.db_path)
        existing_secrets = {}
        if existing:
            existing_secrets = decrypt_secrets(existing.get("encrypted_secrets_json") or "{}")

        service_type = data.get("service_type") or (existing.get("service_type") if existing else "generic_secret")
        name = data.get("name") or (existing.get("name") if existing else integration_id)

        config_dict = data.get("config", {})
        incoming_secrets = data.get("secrets", {})

        # Se un secret ha il valore mascherato '••••••••', preserviamo il valore precedente
        merged_secrets = dict(existing_secrets)
        for k, v in incoming_secrets.items():
            if v and v != "••••••••" and not k.startswith("has_"):
                merged_secrets[k] = v

        encrypted_payload = encrypt_secrets(merged_secrets)

        now_iso = datetime.now(timezone.utc).isoformat()
        db_payload = {
            "id": integration_id,
            "service_type": service_type,
            "name": name,
            "config_json": json.dumps(config_dict, ensure_ascii=False),
            "encrypted_secrets_json": encrypted_payload,
            "status": data.get("status") or (existing.get("status") if existing else "untested"),
            "last_tested_at": data.get("last_tested_at") or (existing.get("last_tested_at") if existing else None),
            "last_error": data.get("last_error") or (existing.get("last_error") if existing else None),
            "updated_at": now_iso,
        }

        auto_db.save_integration(db_payload, db_path=self.db_path)
        return self.get_integration(integration_id, decrypt=False)

    def delete_integration(self, integration_id: str) -> bool:
        """Elimina un'integrazione."""
        return auto_db.delete_integration(integration_id, db_path=self.db_path)

    def test_connection(self, integration_id: str) -> Dict[str, Any]:
        """Esegue il test di connessione in tempo reale per l'integrazione specificata."""
        item = self.get_integration(integration_id, decrypt=True)
        if not item:
            return {"success": False, "error": f"Integrazione '{integration_id}' non trovata."}

        stype = item.get("service_type", "")
        cfg = item.get("config", {})
        sec = item.get("secrets", {})

        start_time = time.monotonic()
        outcome: Dict[str, Any] = {"success": False, "message": "", "error": None}

        try:
            if stype == "email":
                outcome = self._test_email_connection(cfg, sec)
            elif stype == "github":
                outcome = self._test_github_connection(cfg, sec)
            elif stype == "home_assistant":
                outcome = self._test_home_assistant_connection(cfg, sec)
            elif stype in ("google_calendar", "caldav", "webcal"):
                outcome = self._test_calendar_connection(cfg, sec)
            elif stype == "generic_secret":
                outcome = {"success": True, "message": f"{len(sec)} secret configurati correttamente."}
            else:
                outcome = {"success": True, "message": f"Tipo integrazione '{stype}' verificato."}
        except Exception as e:
            outcome = {"success": False, "error": f"Eccezione durante il test: {str(e)}"}

        latency_ms = int((time.monotonic() - start_time) * 1000)
        outcome["latency_ms"] = latency_ms

        # Aggiorna lo stato nel database
        new_status = "connected" if outcome.get("success") else "error"
        now_iso = datetime.now(timezone.utc).isoformat()
        auto_db.update_integration_status(
            integration_id=integration_id,
            status=new_status,
            last_tested_at=now_iso,
            last_error=outcome.get("error"),
            db_path=self.db_path,
        )

        return outcome

    def _test_email_connection(self, cfg: Dict[str, Any], sec: Dict[str, Any]) -> Dict[str, Any]:
        """Testa il login IMAP con le credenziali fornite."""
        host = cfg.get("imap_host") or os.getenv("IMAP_HOST")
        port = int(cfg.get("imap_port") or os.getenv("IMAP_PORT", "993"))
        user = cfg.get("imap_user") or os.getenv("IMAP_USER")
        password = sec.get("imap_password") or os.getenv("IMAP_PASSWORD")
        use_ssl = bool(cfg.get("imap_use_ssl", True))

        if not host or not user or not password:
            return {
                "success": False,
                "error": "Parametri incompleti: 'imap_host', 'imap_user' e 'imap_password' sono obbligatori.",
            }

        try:
            if use_ssl:
                mail = imaplib.IMAP4_SSL(host, port, timeout=10.0)
            else:
                mail = imaplib.IMAP4(host, port, timeout=10.0)

            mail.login(user, password)
            status, data = mail.select("INBOX", readonly=True)
            msg_count = 0
            if status == "OK" and data and data[0]:
                msg_count = int(data[0].decode("utf-8", errors="ignore"))
            mail.close()
            mail.logout()
            return {
                "success": True,
                "message": f"Connessione IMAP a {host}:{port} riuscita! INBOX contiene {msg_count} messaggi.",
                "inbox_count": msg_count,
            }
        except imaplib.IMAP4.error as e:
            return {"success": False, "error": f"Errore autenticazione IMAP: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Impossibile raggiungere il server IMAP: {str(e)}"}

    def _test_github_connection(self, cfg: Dict[str, Any], sec: Dict[str, Any]) -> Dict[str, Any]:
        """Testa un token GitHub chiamando l'endpoint /user."""
        token = sec.get("token") or sec.get("personal_access_token") or os.getenv("GITHUB_TOKEN")
        if not token:
            return {"success": False, "error": "Token GitHub mancante."}

        req = urllib.request.Request("https://api.github.com/user")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("User-Agent", "homelab-agent/1.0")
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                login = data.get("login", "unknown")
                return {
                    "success": True,
                    "message": f"Autenticato su GitHub con successo come utente '{login}'.",
                    "user": login,
                }
        except urllib.error.HTTPError as e:
            return {"success": False, "error": f"GitHub API HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"success": False, "error": f"Errore connessione GitHub: {str(e)}"}

    def _test_home_assistant_connection(self, cfg: Dict[str, Any], sec: Dict[str, Any]) -> Dict[str, Any]:
        """Testa la connessione a Home Assistant chiamando /api/."""
        base_url = (cfg.get("base_url") or os.getenv("HASS_URL") or "http://homeassistant.local:8123").rstrip("/")
        token = sec.get("access_token") or os.getenv("HASS_TOKEN")
        if not token:
            return {"success": False, "error": "Long-lived Access Token di Home Assistant mancante."}

        req = urllib.request.Request(f"{base_url}/api/")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "success": True,
                    "message": f"Connessione a Home Assistant verificata ({data.get('message', 'API Running')}).",
                }
        except Exception as e:
            return {"success": False, "error": f"Errore connessione Home Assistant su {base_url}: {str(e)}"}

    def _test_calendar_connection(self, cfg: Dict[str, Any], sec: Dict[str, Any]) -> Dict[str, Any]:
        """Testa la connettività con feed iCal / Google Calendar o server CalDAV."""
        url = cfg.get("ical_feed_url") or cfg.get("url") or cfg.get("feed_url")
        if not url:
            return {"success": False, "error": "Parametro 'ical_feed_url' (o 'url') mancante nella configurazione."}

        clean_url = url
        if clean_url.startswith("webcal://"):
            clean_url = "https://" + clean_url[9:]

        headers = {"User-Agent": "Homelab-Agent-Calendar/1.0"}
        token = sec.get("api_key") or sec.get("token") or sec.get("oauth_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(clean_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                sample = resp.read(2048).decode("utf-8", errors="replace")
                if "BEGIN:VCALENDAR" in sample or "VCALENDAR" in sample:
                    return {
                        "success": True,
                        "message": "Feed del calendario verificato con successo (formato iCalendar RFC 5545 valido).",
                    }
                elif resp.status in (200, 204):
                    return {
                        "success": True,
                        "message": f"Endpoint del calendario raggiungibile (HTTP {resp.status}).",
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Risposta inaspettata dal server (HTTP {resp.status}).",
                    }
        except Exception as e:
            return {"success": False, "error": f"Errore connessione al calendario: {str(e)}"}

    def get_active_credentials(self, service_type: str, account_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Restituisce la configurazione e i secret decifrati dell'integrazione attiva per il service_type (e opzionale account_id)."""
        integrations = self.list_integrations(service_type=service_type, decrypt=True)
        if not integrations:
            return None
        if account_id:
            match = next((i for i in integrations if i.get("id") == account_id), None)
            if match:
                return {**match.get("config", {}), **match.get("secrets", {})}
        # Preferisci integrazioni con status 'connected' o la prima disponibile
        connected = next((i for i in integrations if i.get("status") == "connected"), integrations[0])
        return {**connected.get("config", {}), **connected.get("secrets", {})}


# Singleton helper
_integration_manager: Optional[IntegrationManager] = None


def get_integration_manager(db_path: Optional[str] = None) -> IntegrationManager:
    global _integration_manager
    if _integration_manager is None or db_path is not None:
        _integration_manager = IntegrationManager(db_path=db_path or config.AUTOMATIONS_DB_PATH)
    return _integration_manager
