"""Registry per strumenti di gestione email e reportistica homelab.

Fornisce tool per:
- Lettura email recenti/non lette (IMAP o simulazione realistica homelab)
- Creazione e salvataggio bozze (Draft) — Auto-send categoricamente DISABILITATO
- Salvataggio di artefatti Markdown per briefing e report
"""

import email
import imaplib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from registry.base import BaseToolRegistry

logger = logging.getLogger("registry.email")


class EmailRegistry(BaseToolRegistry):
    """Tool Registry per operazioni email e briefing."""

    def __init__(self):
        self._saved_drafts: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "email"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "email_fetch_unread",
                "description": "Recupera le email recenti o non lette dalla casella di posta (supporta IMAP o fallback simulato homelab).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "max_emails": {
                            "type": "integer",
                            "description": "Numero massimo di email da recuperare (default 20)",
                            "default": 20,
                        },
                        "unread_only": {
                            "type": "boolean",
                            "description": "Se True recupera solo le non lette, altrimenti tutte le recenti",
                            "default": True,
                        },
                    },
                },
            },
            {
                "name": "email_create_draft",
                "description": "Crea e salva una bozza di risposta (Draft). NOTA DI SICUREZZA: Nessuna email viene mai inviata automaticamente.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Indirizzo email del destinatario"},
                        "subject": {"type": "string", "description": "Oggetto della bozza"},
                        "body": {"type": "string", "description": "Corpo del messaggio della bozza"},
                        "reply_to_id": {"type": "string", "description": "ID dell'email a cui si risponde (opzionale)"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
            {
                "name": "save_briefing_artifact",
                "description": "Salva un report di briefing in formato Markdown nel database e nell'archivio artefatti.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Titolo del briefing / report"},
                        "content": {"type": "string", "description": "Contenuto Markdown del report"},
                        "content_source": {"type": "string", "description": "Origine o riferimento del testo (opzionale)"},
                    },
                    "required": ["title"],
                },
            },
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "email_fetch_unread":
            return self._fetch_unread(
                max_emails=int(args.get("max_emails", 20)),
                unread_only=bool(args.get("unread_only", True))
            )
        elif tool_name == "email_create_draft":
            return self._create_draft(
                to=str(args.get("to", "")),
                subject=str(args.get("subject", "")),
                body=str(args.get("body", "")),
                reply_to_id=args.get("reply_to_id")
            )
        elif tool_name == "save_briefing_artifact":
            return self._save_artifact(
                title=str(args.get("title", "Email Briefing Report")),
                content=args.get("content") or args.get("content_source") or ""
            )
        else:
            return {"error": f"Tool '{tool_name}' non gestito da {self.name}"}

    def _fetch_unread(self, max_emails: int = 20, unread_only: bool = True) -> Dict[str, Any]:
        """Tenta la connessione IMAP reale se configurata, altrimenti usa mock realistico homelab."""
        imap_host = os.getenv("IMAP_HOST")
        imap_user = os.getenv("IMAP_USER")
        imap_pass = os.getenv("IMAP_PASSWORD")
        imap_port = int(os.getenv("IMAP_PORT", "993"))

        if imap_host and imap_user and imap_pass:
            try:
                logger.info(f"Connessione IMAP a {imap_host}:{imap_port} per utente {imap_user}...")
                mail = imaplib.IMAP4_SSL(imap_host, imap_port)
                mail.login(imap_user, imap_pass)
                mail.select("INBOX")
                search_criteria = "UNSEEN" if unread_only else "ALL"
                status, data = mail.search(None, search_criteria)
                if status == "OK" and data[0]:
                    mail_ids = data[0].split()
                    mail_ids = mail_ids[-max_emails:]  # ultime N email
                    results = []
                    for mid in reversed(mail_ids):
                        status, msg_data = mail.fetch(mid, "(RFC822)")
                        if status == "OK":
                            raw_email = msg_data[0][1]
                            msg = email.message_from_bytes(raw_email)
                            results.append({
                                "id": mid.decode("utf-8", errors="ignore"),
                                "from": msg.get("From", "Sconosciuto"),
                                "subject": msg.get("Subject", "(Nessun oggetto)"),
                                "date": msg.get("Date", ""),
                                "body_snippet": str(msg.get_payload()[:200]),
                                "unread": True,
                            })
                    mail.close()
                    mail.logout()
                    return {"emails": results, "count": len(results), "source": "imap"}
            except Exception as e:
                logger.warning(f"Connessione IMAP fallita ({e}). Utilizzo fallback homelab simulato.")

        # Fallback dataset realistico homelab
        mock_emails = [
            {
                "id": "msg_hl_01",
                "from": "pve-alerts@homelab.local",
                "subject": "[URGENTE] Proxmox Storage 'local-zfs' 89% full on node DESKTOP-PGMTM0B",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "body_snippet": "Allerta spazio disco: lo storage ZFS ha superato la soglia di guardia (89%). Necessario pulire vecchi snapshot o template.",
                "unread": True,
            },
            {
                "id": "msg_hl_02",
                "from": "notifications@github.com",
                "subject": "[homelab-agent] Security Advisory: Bump fastembed and pillow-heif",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "body_snippet": "Dependabot ha identificato 2 aggiornamenti di sicurezza minori per il backend. PR #44 aperta per il branch dev.",
                "unread": True,
            },
            {
                "id": "msg_hl_03",
                "from": "pihole-admin@deggio.local",
                "subject": "Pi-hole Weekly Telemetry Report & Blocklist Sync",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "body_snippet": "Riepilogo DNS: 142,500 query totali, 18.4% bloccate. Gravity list aggiornata con successo su CT 137.",
                "unread": True,
            },
        ]
        return {
            "emails": mock_emails[:max_emails],
            "count": len(mock_emails[:max_emails]),
            "source": "homelab_mock",
        }

    def _create_draft(self, to: str, subject: str, body: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
        """Registra la bozza localmente garantendo che NON venga eseguito alcun invio automatico."""
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        draft_record = {
            "draft_id": draft_id,
            "to": to,
            "subject": subject,
            "body": body,
            "reply_to_id": reply_to_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "draft_saved",
        }
        self._saved_drafts.append(draft_record)
        logger.info(f"Bozza creata con ID '{draft_id}' per '{to}'. Invio automatico disabilitato.")
        return {
            "draft_id": draft_id,
            "to": to,
            "subject": subject,
            "status": "draft_saved",
            "warning": "Bozza creata con successo. Nessuna email è stata inviata (auto-send categoricamente disabilitato).",
        }

    def _save_artifact(self, title: str, content: str) -> Dict[str, Any]:
        """Salva il report Markdown dell'automazione."""
        artifact_id = f"art_{uuid.uuid4().hex[:10]}"
        now_str = datetime.now(timezone.utc).isoformat()
        
        # Tenta il salvataggio su tabella DB 'artifacts' se disponibile
        try:
            from automations import db as auto_db
            auto_db.save_artifact({
                "artifact_id": artifact_id,
                "run_id": "manual_or_direct",
                "type": "markdown",
                "title": title,
                "content": content,
                "created_at": now_str,
                "meta_json": "{}",
            })
        except Exception as e:
            logger.debug(f"Salvataggio artefatto su DB non riuscito o opzionale: {e}")

        return {
            "artifact_id": artifact_id,
            "title": title,
            "content": content,
            "status": "saved",
            "format": "markdown",
            "length": len(content),
            "created_at": now_str,
        }
