"""Registry per strumenti di gestione e ispezione delle Automazioni Homelab.

Fornisce all'agente tool per:
- Elencare e ispezionare i template canonici disponibili (es. Daily Email Briefing, GitHub Issue Repair)
- Elencare e ispezionare le automazioni attualmente registrate nel database
- Installare un'automazione a partire da un template (con eventuale personalizzazione orario cron)
- Creare automazioni custom strutturate
- Eseguire o simulare (dry-run) una specifica automazione
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from automations import db as auto_db
from automations.models import AutomationDefinition
from registry.base import BaseToolRegistry

logger = logging.getLogger("registry.automations")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "automations" / "templates"


class AutomationRegistry(BaseToolRegistry):
    """Tool Registry per la gestione delle automazioni e dei template."""

    @property
    def name(self) -> str:
        return "automations"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "list_automation_templates",
                "description": (
                    "Elenca i template pre-configurati di automazione disponibili nel sistema "
                    "(es. Daily Email Briefing, GitHub Issue Auto-Repair Loop) con le rispettive descrizioni, "
                    "trigger schedulati, step e strumenti autorizzati."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_automations",
                "description": (
                    "Elenca tutte le automazioni attualmente installate e registrate nel database di homelab-agent, "
                    "con il rispettivo stato (attiva/disabilitata), schedulazione cron e trigger."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "enabled_only": {
                            "type": "boolean",
                            "description": "Se True, restituisce solo le automazioni abilitate.",
                            "default": False,
                        }
                    },
                },
            },
            {
                "name": "get_automation_details",
                "description": (
                    "Recupera la definizione completa di un'automazione specifica tramite il suo ID "
                    "(o di un template se non ancora installata), inclusi gli step di workflow e le policy di sicurezza."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "automation_id": {
                            "type": "string",
                            "description": "L'ID dell'automazione o del template (es. 'tpl-daily-email-briefing').",
                        }
                    },
                    "required": ["automation_id"],
                },
            },
            {
                "name": "create_automation_from_template",
                "description": (
                    "Installa e attiva un'automazione nel sistema a partire da un template esistente. "
                    "Consente di personalizzare il nome e l'orario di schedulazione cron (es. '0 8 * * 1-5' per le 08:00 dal lunedì al venerdì)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_id": {
                            "type": "string",
                            "description": "ID del template sorgente (es. 'tpl-daily-email-briefing' o 'tpl-github-issue-repair').",
                        },
                        "custom_name": {
                            "type": "string",
                            "description": "Nome personalizzato opzionale per l'automazione.",
                        },
                        "custom_cron": {
                            "type": "string",
                            "description": "Espressione cron opzionale per ridefinire la frequenza di esecuzione (es. '0 9 * * *').",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "Se attivare immediatamente l'automazione dopo la creazione.",
                            "default": True,
                        },
                    },
                    "required": ["template_id"],
                },
            },
            {
                "name": "create_custom_automation",
                "description": (
                    "Crea e registra nel database un'automazione completamente personalizzata con trigger, step di workflow "
                    "(azioni deterministiche o task agentici) e policy di sicurezza."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "automation_def": {
                            "type": "object",
                            "description": (
                                "Oggetto JSON conforme ad AutomationDefinition. Campi: id (univoco), name (titolo), "
                                "description (spiegazione), triggers (array trigger), workflow (oggetto con initial_step_id e steps), "
                                "permission_policy (oggetto con allowed_tools e security_mode), budget (guardrail risorse)."
                            ),
                            "properties": {
                                "id": {"type": "string", "description": "ID univoco in snake_case (es. 'auto_github_trending')"},
                                "name": {"type": "string", "description": "Nome descrittivo dell'automazione"},
                                "description": {"type": "string", "description": "Descrizione chiara del task"},
                                "triggers": {
                                    "type": "array",
                                    "description": "Trigger di avvio (cron o manuale)",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "type": {"type": "string", "enum": ["cron", "manual"]},
                                            "cron_expression": {"type": "string", "description": "Espressione cron standard (es. '0 12 * * *')"},
                                            "timezone": {"type": "string", "default": "Europe/Rome"}
                                        }
                                    }
                                },
                                "workflow": {
                                    "type": "object",
                                    "description": "Flusso di esecuzione a step",
                                    "properties": {
                                        "initial_step_id": {"type": "string", "description": "ID del primo step da eseguire (es. 'step_1')"},
                                        "steps": {
                                            "type": "array",
                                            "description": "Lista ordinata degli step",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "step_id": {"type": "string", "description": "ID univoco step (es. 'step_1_search')"},
                                                    "name": {"type": "string", "description": "Titolo step"},
                                                    "type": {"type": "string", "enum": ["deterministic_action", "agentic_task", "approval_gate"]},
                                                    "action_or_tool": {"type": "string", "description": "Nome tool (es. 'web_search', 'save_artifact', 'http_get')"},
                                                    "parameters": {"type": "object", "description": "Argomenti del tool (es. {'query': '...'})"},
                                                    "prompt_template": {"type": "string", "description": "Prompt per step agentici"}
                                                },
                                                "required": ["step_id", "type"]
                                            }
                                        }
                                    },
                                    "required": ["initial_step_id", "steps"]
                                },
                                "permission_policy": {
                                    "type": "object",
                                    "description": "Policy di sicurezza e tool consentiti",
                                    "properties": {
                                        "allowed_tools": {"type": "array", "items": {"type": "string"}},
                                        "security_mode": {"type": "string", "enum": ["safest", "normal", "dangerous"], "default": "normal"}
                                    }
                                },
                                "budget": {
                                    "type": "object",
                                    "description": "Guardrail di risorse e sicurezza per la run (opzionale, default sicuri se omesso)",
                                    "properties": {
                                        "max_duration_seconds": {"type": "integer", "default": 300, "description": "Timeout globale run in secondi"},
                                        "max_tokens": {"type": "integer", "default": 50000, "description": "Tetto token consumabili per run"},
                                        "max_llm_calls": {"type": "integer", "default": 10, "description": "Numero max chiamate LLM"},
                                        "max_tool_calls": {"type": "integer", "default": 25, "description": "Numero max tool invocabili"},
                                        "max_retries_per_step": {"type": "integer", "default": 2, "description": "Tentativi retry per step fallito"}
                                    }
                                }
                            },
                            "required": ["name", "workflow"]
                        }
                    },
                    "required": ["automation_def"],
                },
            },
            {
                "name": "update_automation",
                "description": (
                    "Aggiorna o modifica un'automazione esistente (es. per modificare i prompt degli step, "
                    "aggiungere/rimuovere step, modificare orari cron, parametri o budget). "
                    "Non crea duplicati ma aggiorna la definizione esistente."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "automation_id": {
                            "type": "string",
                            "description": "ID dell'automazione da modificare (es. 'auto_github_trending').",
                        },
                        "updates": {
                            "type": "object",
                            "description": (
                                "Campi da aggiornare nella definizione (es. name, description, workflow, "
                                "triggers, budget, permission_policy, enabled, retention_days)."
                            ),
                        },
                    },
                    "required": ["automation_id", "updates"],
                },
            },
            {
                "name": "trigger_automation_run",
                "description": (
                    "Avvia immediatamente un'esecuzione di un'automazione registrata. "
                    "Supporta la modalità dry_run per testare il flusso in anteprima sicura senza side effect."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "automation_id": {
                            "type": "string",
                            "description": "ID dell'automazione da eseguire.",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "Se True, esegue una simulazione sicura senza modificare dati esterni.",
                            "default": False,
                        },
                    },
                    "required": ["automation_id"],
                },
            },
            {
                "name": "save_artifact",
                "description": (
                    "Salva un report o artefatto generato (Markdown, JSON o testo) nell'archivio persistente del sistema e nel database."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Titolo dell'artefatto o del report."
                        },
                        "content": {
                            "type": "string",
                            "description": "Testo o markdown del contenuto da archiviare."
                        },
                        "content_source": {
                            "type": "string",
                            "description": "Sorgente o riferimento alternativo per il contenuto."
                        },
                        "path": {
                            "type": "string",
                            "description": "Percorso facoltativo su filesystem in cui persistere il file."
                        },
                        "type": {
                            "type": "string",
                            "description": "Tipo dell'artefatto (default 'report').",
                            "default": "report"
                        }
                    },
                    "required": ["title"]
                },
            },
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "list_automation_templates":
            return self._list_templates()
        elif tool_name == "list_automations":
            enabled_only = args.get("enabled_only", False)
            return self._list_automations(enabled_only=enabled_only)
        elif tool_name == "get_automation_details":
            return self._get_details(args.get("automation_id", ""))
        elif tool_name == "create_automation_from_template":
            return self._create_from_template(
                template_id=args.get("template_id", ""),
                custom_name=args.get("custom_name"),
                custom_cron=args.get("custom_cron"),
                enabled=args.get("enabled", True),
            )
        elif tool_name == "create_custom_automation":
            return self._create_custom(args.get("automation_def", {}))
        elif tool_name == "update_automation":
            return self._update_automation(args.get("automation_id", ""), args.get("updates", {}))
        elif tool_name == "trigger_automation_run":
            return self._trigger_run(
                automation_id=args.get("automation_id", ""),
                dry_run=args.get("dry_run", False),
            )
        elif tool_name in ("save_artifact", "save_report", "file_write", "write_file", "save_file"):
            return self._save_artifact(args)
        else:
            return {"error": f"Tool '{tool_name}' non gestito dal registry 'automations'."}

    def _save_artifact(self, args: Dict[str, Any]) -> Dict[str, Any]:
        import uuid
        from datetime import datetime, timezone
        from pathlib import Path
        title = args.get("title") or args.get("name") or "Report Automazione"
        content = args.get("content") or args.get("content_source") or args.get("body") or ""
        art_type = args.get("type", "report")
        target_path = args.get("path") or args.get("filename") or args.get("target_path") or args.get("storage_uri")
        run_id = args.get("run_id") or args.get("_run_id") or "manual_or_direct"
        step_run_id = args.get("step_run_id") or args.get("_step_run_id")

        art_id = f"art_{uuid.uuid4().hex[:10]}"
        now_str = datetime.now(timezone.utc).isoformat()

        storage_uri = target_path or f"/data/artifacts/{art_id}.md"
        try:
            p = Path(storage_uri)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(content), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Impossibile salvare artefatto su file ({storage_uri}): {e}")
            storage_uri = f"db://artifacts/{art_id}"

        try:
            auto_db.save_artifact({
                "artifact_id": art_id,
                "run_id": run_id,
                "step_run_id": step_run_id,
                "name": title,
                "type": art_type,
                "mime_type": "text/markdown" if "md" in storage_uri else "text/plain",
                "storage_uri": storage_uri,
                "created_at": now_str,
            }, db_path=config.AUTOMATIONS_DB_PATH)
        except Exception as ex:
            logger.warning(f"Errore salvataggio metadati artefatto su DB: {ex}")

        return {
            "artifact_id": art_id,
            "run_id": run_id,
            "title": title,
            "content": str(content),
            "storage_uri": storage_uri,
            "status": "saved",
            "message": f"Artefatto '{title}' salvato con successo."
        }

    def _list_templates(self) -> List[Dict[str, Any]]:
        templates = []
        if TEMPLATES_DIR.exists():
            for f in sorted(TEMPLATES_DIR.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                        templates.append({
                            "id": data.get("id"),
                            "template_id": data.get("id"),
                            "name": data.get("name"),
                            "description": data.get("description"),
                            "triggers": [
                                {
                                    "type": t.get("type"),
                                    "cron_expression": t.get("cron_expression"),
                                    "timezone": t.get("timezone", "Europe/Rome"),
                                }
                                for t in data.get("triggers", [])
                            ],
                            "steps_count": len(data.get("workflow", {}).get("steps", [])),
                            "steps_summary": [
                                s.get("name") or s.get("step_id")
                                for s in data.get("workflow", {}).get("steps", [])
                            ],
                            "allowed_tools": data.get("permission_policy", {}).get("allowed_tools", []),
                        })
                except Exception as e:
                    logger.warning(f"Errore caricamento template {f}: {e}")
        return templates

    def _list_automations(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        autos = auto_db.list_automations(enabled_only=enabled_only, db_path=config.AUTOMATIONS_DB_PATH)
        result = []
        for a in autos:
            triggers_summary = []
            for t in a.get("triggers", []):
                triggers_summary.append(
                    f"{t.get('type')}" + (f": {t.get('cron_expression')}" if t.get("cron_expression") else "")
                )
            result.append({
                "id": a.get("id"),
                "name": a.get("name"),
                "description": a.get("description"),
                "enabled": a.get("enabled"),
                "version": a.get("version"),
                "triggers": triggers_summary,
                "created_at": a.get("created_at"),
            })
        return result

    def _get_details(self, automation_id: str) -> Dict[str, Any]:
        if not automation_id:
            return {"error": "automation_id obbligatorio."}

        auto = auto_db.get_automation(automation_id, db_path=config.AUTOMATIONS_DB_PATH)
        if auto:
            return auto

        # Se non trovata nelle attive, cerca nei template
        if TEMPLATES_DIR.exists():
            for f in TEMPLATES_DIR.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        tpl = json.load(fp)
                        tid = tpl.get("id", "")
                        clean_aid = automation_id.lower().replace("-", "_")
                        clean_tid = tid.lower().replace("-", "_")
                        if (
                            tid == automation_id
                            or clean_tid == clean_aid
                            or f.stem == clean_aid
                            or ("email" in clean_aid and "email" in clean_tid)
                            or ("repair" in clean_aid and "repair" in clean_tid)
                        ):
                            tpl["_is_template"] = True
                            return tpl
                except Exception:
                    pass

        return {"error": f"Automazione o template '{automation_id}' non trovata."}

    def _create_from_template(
        self,
        template_id: str,
        custom_name: Optional[str] = None,
        custom_cron: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        target_file = None
        if TEMPLATES_DIR.exists():
            for f in TEMPLATES_DIR.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                        tid = data.get("id", "")
                        clean_tid = tid.lower().replace("-", "_")
                        clean_target = template_id.lower().replace("-", "_")
                        if (
                            tid == template_id
                            or clean_tid == clean_target
                            or f.stem == clean_target
                            or ("email" in clean_target and "email" in clean_tid)
                            or ("repair" in clean_target and "repair" in clean_tid)
                        ):
                            target_file = f
                            break
                except Exception:
                    pass

        if not target_file:
            return {"error": f"Template '{template_id}' non trovato."}

        with open(target_file, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        if custom_name:
            data["name"] = custom_name
        data["enabled"] = enabled

        # Assegna un ID operativo univoco distinto dal template
        base_id = data.get("id", "auto").replace("tpl-", "auto-").replace("tpl_", "auto_")
        candidate_id = base_id
        if auto_db.get_definition(candidate_id, db_path=config.AUTOMATIONS_DB_PATH):
            import uuid
            candidate_id = f"{base_id}_{uuid.uuid4().hex[:6]}"
        data["id"] = candidate_id

        if custom_cron:
            for trg in data.get("triggers", []):
                if trg.get("type") == "cron":
                    trg["cron_expression"] = custom_cron

        try:
            auto_def = AutomationDefinition(**data)
            saved = auto_db.save_automation(auto_def.model_dump(mode="json"), db_path=config.AUTOMATIONS_DB_PATH)

            # Sincronizza lo scheduler in background
            try:
                from automations.scheduler import get_scheduler
                sched = get_scheduler()
                sched.sync_triggers()
            except Exception as e:
                logger.warning(f"Sincronizzazione scheduler dopo creazione template non riuscita: {e}")

            return {
                "status": "created",
                "automation_id": saved.get("id"),
                "name": saved.get("name"),
                "enabled": saved.get("enabled"),
                "message": f"Automazione '{saved.get('name')}' creata e attivata con successo!",
            }
        except Exception as e:
            return {"error": f"Errore validazione automazione: {str(e)}"}

    def _create_custom(self, automation_def: Dict[str, Any]) -> Dict[str, Any]:
        if not automation_def or not isinstance(automation_def, dict):
            return {"error": "automation_def deve essere un oggetto JSON valido."}

        try:
            # Preprocessing difensivo: ripulisce chiavi con valore None o stringhe vuote non desiderate
            sanitized_def = {k: v for k, v in automation_def.items() if v is not None}
            auto_obj = AutomationDefinition(**sanitized_def)

            # Pre-flight Validation
            step_ids = [s.step_id for s in auto_obj.workflow.steps]
            if not step_ids:
                return {"error": "Il workflow deve contenere almeno uno step."}
            if auto_obj.workflow.initial_step_id not in step_ids:
                return {
                    "error": (
                        f"initial_step_id '{auto_obj.workflow.initial_step_id}' non corrisponde a nessuno "
                        f"degli step definiti ({step_ids}). Correggi initial_step_id in modo che coincida "
                        f"con il primo step."
                    )
                }

            # Validazione parametri minimi per tool comuni
            for s in auto_obj.workflow.steps:
                if s.action_or_tool == "web_search" and "query" not in s.parameters:
                    return {
                        "error": (
                            f"Nello step '{s.step_id}', il tool 'web_search' richiede il parametro 'query' "
                            f"all'interno di 'parameters': {{'query': '...'}}. Parametri attuali: {s.parameters}"
                        )
                    }

            saved = auto_db.save_automation(auto_obj.model_dump(mode="json"), db_path=config.AUTOMATIONS_DB_PATH)

            try:
                from automations.scheduler import get_scheduler
                sched = get_scheduler()
                sched.sync_triggers()
            except Exception as e:
                logger.warning(f"Sincronizzazione scheduler dopo creazione custom non riuscita: {e}")

            return {
                "status": "created",
                "automation_id": saved.get("id"),
                "name": saved.get("name"),
                "enabled": saved.get("enabled"),
                "message": f"Automazione personalizzata '{saved.get('name')}' registrata con successo!",
            }
        except Exception as e:
            return {"error": f"Errore durante la creazione dell'automazione custom: {str(e)}"}

    def _update_automation(self, automation_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if not automation_id:
            return {"error": "automation_id obbligatorio."}
        if not updates or not isinstance(updates, dict):
            return {"error": "updates deve essere un oggetto JSON con i campi da aggiornare."}

        existing = auto_db.get_automation(automation_id, db_path=config.AUTOMATIONS_DB_PATH)
        if not existing:
            return {"error": f"Automazione '{automation_id}' non trovata."}

        try:
            merged = dict(existing)
            for k, v in updates.items():
                if v is not None:
                    if k in ("workflow", "budget", "permission_policy", "parameters", "settings") and isinstance(v, dict) and isinstance(merged.get(k), dict):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v

            merged["id"] = automation_id
            merged["version"] = int(existing.get("version", 1)) + 1

            clean_def = {k: v for k, v in merged.items() if v is not None}
            auto_obj = AutomationDefinition(**clean_def)

            step_ids = [s.step_id for s in auto_obj.workflow.steps]
            if not step_ids:
                return {"error": "Il workflow deve contenere almeno uno step."}
            if auto_obj.workflow.initial_step_id not in step_ids:
                return {
                    "error": (
                        f"initial_step_id '{auto_obj.workflow.initial_step_id}' non corrisponde a nessuno "
                        f"degli step definiti ({step_ids})."
                    )
                }

            saved = auto_db.save_automation(auto_obj.model_dump(mode="json"), db_path=config.AUTOMATIONS_DB_PATH)

            try:
                from automations.scheduler import get_scheduler
                sched = get_scheduler()
                if sched.is_running:
                    sched.sync_triggers()
            except Exception as e:
                logger.warning(f"Sincronizzazione scheduler dopo update non riuscita: {e}")

            return {
                "status": "updated",
                "automation_id": saved.get("id"),
                "name": saved.get("name"),
                "version": saved.get("version"),
                "enabled": saved.get("enabled"),
                "message": f"Automazione '{saved.get('name')}' aggiornata con successo (versione {saved.get('version')})!",
            }
        except Exception as e:
            return {"error": f"Errore durante l'aggiornamento dell'automazione: {str(e)}"}

    def _trigger_run(self, automation_id: str, dry_run: bool = False) -> Dict[str, Any]:
        if not automation_id:
            return {"error": "automation_id obbligatorio."}

        try:
            from automations.runner import get_runner
            runner = get_runner()
            res = runner.execute_run(
                automation_id=automation_id,
                trigger_type="manual",
                trigger_payload={"triggered_by": "agent_chat"},
                dry_run=dry_run,
            )
            return {
                "status": res.status.value,
                "run_id": res.run_id,
                "automation_id": automation_id,
                "is_dry_run": res.is_dry_run,
                "total_duration_ms": res.total_duration_ms,
                "total_tokens": res.total_tokens,
                "message": f"Esecuzione ({'Dry-Run' if dry_run else 'Standard'}) completata con stato '{res.status.value}'.",
            }
        except Exception as e:
            return {"error": f"Errore esecuzione automazione '{automation_id}': {str(e)}"}
