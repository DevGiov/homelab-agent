"""Background Cron Scheduler per Automations & Loops.

Gestisce la pianificazione temporizzata delle automazioni basata su cron expression
utilizzando APScheduler (AsyncIOScheduler), con sincronizzazione automatica dal database
persistente `automations.db`.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from automations import db as auto_db
from automations.models import AutomationDefinition, TriggerType
from automations.runner import AutomationRunner

logger = logging.getLogger("automations.scheduler")


class AutomationScheduler:
    """Manager per lo scheduling asincrono di automazioni con trigger cron."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.AUTOMATIONS_DB_PATH
        self.scheduler = AsyncIOScheduler()
        self.runner = AutomationRunner(db_path=self.db_path)
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self):
        """Avvia lo scheduler e carica i trigger attivi dal database."""
        if self._is_running:
            logger.info("Scheduler automazioni già in esecuzione.")
            return

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            self.scheduler = AsyncIOScheduler(event_loop=loop)
            self.scheduler.start()
            self._is_running = True
            logger.info("APScheduler avviato con successo.")
            self.sync_triggers()
            self._schedule_retention_cleanup()
        except Exception as e:
            logger.error(f"Errore durante l'avvio dello scheduler: {e}", exc_info=True)
            self._is_running = False

    def stop(self):
        """Arresta lo scheduler in modo pulito."""
        if not self._is_running:
            return

        try:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("APScheduler arrestato.")
        except Exception as e:
            logger.error(f"Errore durante l'arresto dello scheduler: {e}", exc_info=True)

    def sync_triggers(self):
        """Sincronizza tutti i job cron dal database persistente."""
        if not self._is_running:
            logger.warning("Impossibile sincronizzare i trigger: scheduler non avviato.")
            return

        # Rimuove job gestiti precedenti
        for job in self.scheduler.get_jobs():
            if job.id.startswith("auto_job_"):
                self.scheduler.remove_job(job.id)

        # Recupera definizioni attive dal DB
        definitions = auto_db.list_definitions(enabled_only=True, db_path=self.db_path)
        scheduled_count = 0

        for def_dict in definitions:
            try:
                auto_def = AutomationDefinition(**def_dict)
                for trg in auto_def.triggers:
                    if trg.type == TriggerType.CRON and trg.enabled and trg.cron_expression:
                        self._schedule_trigger(auto_def, trg)
                        scheduled_count += 1
            except Exception as e:
                logger.error(f"Errore parsing/scheduling automazione '{def_dict.get('id')}': {e}")

        logger.info(f"Sincronizzazione completata: {scheduled_count} trigger cron pianificati.")

    # Alias per retrocompatibilità e chiamate da registry/tool
    sync_from_db = sync_triggers

    def _schedule_trigger(self, auto_def: AutomationDefinition, trigger):
        """Pianifica un singolo trigger cron."""
        job_id = f"auto_job_{auto_def.id}_{trigger.id}"
        tz = getattr(trigger, "timezone", "Europe/Rome") or "Europe/Rome"

        try:
            cron_trigger = CronTrigger.from_crontab(trigger.cron_expression, timezone=tz)
            self.scheduler.add_job(
                func=self._execute_scheduled_run,
                trigger=cron_trigger,
                id=job_id,
                name=f"Cron {auto_def.name} ({trigger.cron_expression})",
                args=[auto_def.id, trigger.id],
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info(
                f"Pianificato cron job '{job_id}' per automazione '{auto_def.id}' "
                f"({trigger.cron_expression}, tz={tz})"
            )
        except Exception as e:
            logger.error(f"Espressione cron '{trigger.cron_expression}' non valida per '{auto_def.id}': {e}")

    async def _execute_scheduled_run(self, auto_id: str, trigger_id: str):
        """Callback asincrono invocato da APScheduler al trigger del cron."""
        logger.info(f"Trigger cron attivato per automazione '{auto_id}' (trigger='{trigger_id}')")
        try:
            # Creazione run persistente
            run = self.runner.create_run(
                automation_id=auto_id,
                trigger_type=TriggerType.CRON,
                trigger_id=trigger_id,
                is_dry_run=False,
            )
            # Esecuzione asincrona/in background per non bloccare il loop dello scheduler
            asyncio.create_task(self._run_async(run.run_id))
        except Exception as e:
            logger.error(f"Errore avvio esecuzione pianificata per '{auto_id}': {e}", exc_info=True)

    async def _run_async(self, run_id: str):
        """Esegue il runner in un thread executor per non bloccare l'event loop di asyncio."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self.runner.execute_run, run_id)
            logger.info(f"Esecuzione pianificata della run '{run_id}' terminata.")
        except Exception as e:
            logger.error(f"Errore durante l'esecuzione asincrona della run '{run_id}': {e}", exc_info=True)

    def _schedule_retention_cleanup(self):
        """Pianifica la pulizia periodica notturna delle run storiche obsolete."""
        job_id = "auto_retention_cleanup"
        try:
            cron_trigger = CronTrigger.from_crontab("30 3 * * *", timezone="Europe/Rome")
            self.scheduler.add_job(
                func=self._execute_retention_cleanup,
                trigger=cron_trigger,
                id=job_id,
                name="Automations Run Retention Cleanup",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info("Pianificato job di auto-retention cleanup alle 03:30 Europe/Rome.")
        except Exception as e:
            logger.error(f"Errore pianificazione retention cleanup: {e}")

    async def _execute_retention_cleanup(self):
        """Esegue il prune delle run scadute in background in base alla retention configurata."""
        logger.info("Avvio procedura periodica di auto-retention cleanup per le run...")
        loop = asyncio.get_running_loop()
        try:
            deleted_count = await loop.run_in_executor(None, self._prune_expired_runs)
            logger.info(f"Auto-retention cleanup completato: {deleted_count} run rimosse.")
        except Exception as e:
            logger.error(f"Errore durante l'esecuzione di auto-retention cleanup: {e}", exc_info=True)

    def _prune_expired_runs(self) -> int:
        """Pulisce le run scadute rispettando retention_days di ciascuna automazione (default 14 giorni)."""
        defs = auto_db.list_definitions(enabled_only=False, db_path=self.db_path)
        total_deleted = 0
        global_retention_days = 14

        for d in defs:
            retention = d.get("retention_days") or global_retention_days
            deleted = auto_db.bulk_delete_runs(
                automation_id=d["id"],
                older_than_days=retention,
                db_path=self.db_path,
            )
            total_deleted += deleted

        total_deleted += auto_db.bulk_delete_runs(
            older_than_days=global_retention_days,
            db_path=self.db_path,
        )
        return total_deleted

    def get_scheduled_jobs(self, include_internal: bool = False) -> List[Dict[str, Any]]:
        """Restituisce l'elenco dei job attualmente pianificati nello scheduler."""
        jobs = []
        for job in self.scheduler.get_jobs():
            if not include_internal and job.id == "auto_retention_cleanup":
                continue
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs.append({
                "job_id": job.id,
                "name": job.name,
                "next_run_time": next_run,
                "trigger": str(job.trigger),
            })
        return jobs


# Singleton globale dello scheduler
_SCHEDULER_INSTANCE: Optional[AutomationScheduler] = None


def get_scheduler(db_path: Optional[str] = None) -> AutomationScheduler:
    global _SCHEDULER_INSTANCE
    if _SCHEDULER_INSTANCE is None:
        _SCHEDULER_INSTANCE = AutomationScheduler(db_path=db_path)
    return _SCHEDULER_INSTANCE
