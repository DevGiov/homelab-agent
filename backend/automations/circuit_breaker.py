"""Circuit Breaker & Rate Limiter per Automations & Loops (Milestone M4).

Previene loop infiniti, consumi anomali di token e cascading failures
attraverso tre stati:
- CLOSED: Operatività normale.
- OPEN: Circuito scattato (blocco immediato delle esecuzioni per N fallimenti o superamento rate limit).
- HALF_OPEN: Periodo di prova post-cooldown per verificare il ripristino del workflow.
"""

import logging
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, Optional, Tuple

import config
from automations import db as auto_db
from automations.models import Budget

logger = logging.getLogger("automations.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """Eccezione sollevata quando un'automazione viene bloccata dal circuit breaker."""
    pass


class CircuitBreakerManager:
    """Gestisce la sicurezza a runtime e il rate-limiting delle automazioni."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.AUTOMATIONS_DB_PATH
        self.default_max_consecutive_failures = 3
        self.default_max_runs_per_hour = 30
        self.default_max_daily_tokens = 100000
        self.default_cooldown_seconds = 1800  # 30 minuti

    def check_execution_allowed(
        self,
        automation_id: str,
        budget: Optional[Budget] = None,
        max_runs_per_hour: Optional[int] = None,
        max_daily_tokens: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Verifica se l'automazione può essere eseguita o deve essere bloccata."""
        state_data = auto_db.get_circuit_breaker_state(automation_id, db_path=self.db_path)
        now = datetime.now(timezone.utc)

        if state_data:
            state = state_data.get("state", CircuitState.CLOSED.value)
            tripped_at_str = state_data.get("tripped_at")
            cooldown = state_data.get("cooldown_seconds", self.default_cooldown_seconds)

            # Se il circuito è aperto, verifica se il cooldown è trascorso
            if state == CircuitState.OPEN.value:
                if tripped_at_str:
                    try:
                        tripped_at = datetime.fromisoformat(tripped_at_str)
                        if (now - tripped_at).total_seconds() >= cooldown:
                            logger.info(f"Cooldown trascorso per '{automation_id}'. Transizione a HALF_OPEN.")
                            self._set_state(automation_id, CircuitState.HALF_OPEN.value)
                            return True, None
                    except Exception as e:
                        logger.warning(f"Errore parsing tripped_at '{tripped_at_str}': {e}")

                reason = (
                    f"Circuit Breaker APERTO per '{automation_id}'. "
                    f"Bloccate esecuzioni a causa di {state_data.get('consecutive_failures')} fallimenti consecutivi. "
                    f"Ultimo errore: {state_data.get('last_failure_reason')}"
                )
                return False, reason

        # Controllo Rate Limit Orario (max runs/hour)
        limit_runs = max_runs_per_hour or self.default_max_runs_per_hour
        recent_runs = auto_db.count_recent_runs(automation_id, window_seconds=3600, db_path=self.db_path)
        if recent_runs >= limit_runs:
            reason = (
                f"Rate limit orario superato per '{automation_id}': "
                f"{recent_runs} run nell'ultima ora (limite={limit_runs}/h)."
            )
            logger.warning(f"Circuit Breaker trigger: {reason}")
            return False, reason

        # Controllo Tetto Massimo Token Giornalieri (max tokens/day)
        limit_tokens = max_daily_tokens or self.default_max_daily_tokens
        recent_tokens = auto_db.sum_recent_tokens(automation_id, window_seconds=86400, db_path=self.db_path)
        if recent_tokens >= limit_tokens:
            reason = (
                f"Budget token giornaliero esaurito per '{automation_id}': "
                f"{recent_tokens} token consumati nelle ultime 24h (limite={limit_tokens})."
            )
            logger.warning(f"Circuit Breaker trigger: {reason}")
            return False, reason

        return True, None

    def record_success(self, automation_id: str):
        """Registra un'esecuzione completata con successo, ripristinando CLOSED."""
        state_data = auto_db.get_circuit_breaker_state(automation_id, db_path=self.db_path)
        if state_data and (state_data.get("state") != CircuitState.CLOSED.value or state_data.get("consecutive_failures", 0) > 0):
            logger.info(f"Ripristino Circuit Breaker a CLOSED per '{automation_id}' dopo esito positivo.")
        
        auto_db.save_circuit_breaker_state({
            "automation_id": automation_id,
            "state": CircuitState.CLOSED.value,
            "consecutive_failures": 0,
            "last_failure_reason": None,
            "tripped_at": None,
            "cooldown_seconds": self.default_cooldown_seconds,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, db_path=self.db_path)

    def record_failure(
        self,
        automation_id: str,
        error_message: str,
        max_consecutive_failures: Optional[int] = None,
        cooldown_seconds: Optional[int] = None,
    ):
        """Registra un fallimento e fa scattare il circuito se si supera la soglia."""
        state_data = auto_db.get_circuit_breaker_state(automation_id, db_path=self.db_path) or {}
        current_failures = int(state_data.get("consecutive_failures", 0)) + 1
        threshold = max_consecutive_failures or self.default_max_consecutive_failures
        cooldown = cooldown_seconds or self.default_cooldown_seconds

        now_str = datetime.now(timezone.utc).isoformat()
        if current_failures >= threshold:
            logger.error(
                f"Circuit Breaker SCATTATO (OPEN) per '{automation_id}'! "
                f"Raggiunti {current_failures}/{threshold} fallimenti consecutivi. Errore: {error_message}"
            )
            new_state = CircuitState.OPEN.value
            tripped_at = now_str
        else:
            new_state = state_data.get("state", CircuitState.CLOSED.value)
            tripped_at = state_data.get("tripped_at")
            logger.warning(
                f"Fallimento registrato per '{automation_id}': {current_failures}/{threshold} tentativi prima del blocco."
            )

        auto_db.save_circuit_breaker_state({
            "automation_id": automation_id,
            "state": new_state,
            "consecutive_failures": current_failures,
            "last_failure_reason": error_message,
            "tripped_at": tripped_at,
            "cooldown_seconds": cooldown,
            "updated_at": now_str,
        }, db_path=self.db_path)

    def reset(self, automation_id: str):
        """Reimposta manualmente il circuito a CLOSED."""
        logger.info(f"Reset manuale del Circuit Breaker per '{automation_id}'.")
        auto_db.save_circuit_breaker_state({
            "automation_id": automation_id,
            "state": CircuitState.CLOSED.value,
            "consecutive_failures": 0,
            "last_failure_reason": None,
            "tripped_at": None,
            "cooldown_seconds": self.default_cooldown_seconds,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, db_path=self.db_path)

    def get_status(self, automation_id: str) -> Dict[str, Any]:
        """Restituisce lo stato diagnostico completo del circuit breaker per l'automazione."""
        state_data = auto_db.get_circuit_breaker_state(automation_id, db_path=self.db_path) or {}
        recent_runs = auto_db.count_recent_runs(automation_id, window_seconds=3600, db_path=self.db_path)
        recent_tokens = auto_db.sum_recent_tokens(automation_id, window_seconds=86400, db_path=self.db_path)

        return {
            "automation_id": automation_id,
            "state": state_data.get("state", CircuitState.CLOSED.value),
            "consecutive_failures": state_data.get("consecutive_failures", 0),
            "last_failure_reason": state_data.get("last_failure_reason"),
            "tripped_at": state_data.get("tripped_at"),
            "cooldown_seconds": state_data.get("cooldown_seconds", self.default_cooldown_seconds),
            "recent_runs_1h": recent_runs,
            "max_runs_per_hour": self.default_max_runs_per_hour,
            "recent_tokens_24h": recent_tokens,
            "max_daily_tokens": self.default_max_daily_tokens,
        }

    def _set_state(self, automation_id: str, new_state: str):
        state_data = auto_db.get_circuit_breaker_state(automation_id, db_path=self.db_path) or {"automation_id": automation_id}
        state_data["state"] = new_state
        state_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        auto_db.save_circuit_breaker_state(state_data, db_path=self.db_path)


# Singleton
_CIRCUIT_BREAKER_INSTANCE: Optional[CircuitBreakerManager] = None


def get_circuit_breaker(db_path: Optional[str] = None) -> CircuitBreakerManager:
    global _CIRCUIT_BREAKER_INSTANCE
    if _CIRCUIT_BREAKER_INSTANCE is None:
        _CIRCUIT_BREAKER_INSTANCE = CircuitBreakerManager(db_path=db_path)
    return _CIRCUIT_BREAKER_INSTANCE
