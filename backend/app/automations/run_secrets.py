"""Secrets disponibili a una run, raccolti su tre livelli in ordine di precedenza crescente.

1. Integrazioni di servizio (filtrate dalla `secrets_whitelist` della policy), con l'account
   scelto per tipo di servizio in `settings.integrations` dell'automazione.
2. Secrets scritti direttamente in `settings.secrets` dell'automazione.
3. Variabili d'ambiente del backend, solo per i nomi in whitelist non già risolti.
"""
import logging
import os
from typing import Dict, Optional

from app.automations.models import AutomationDefinition
from app.integrations.manager import get_integration_manager

logger = logging.getLogger("automations.secrets")


def collect_secrets(auto_def: AutomationDefinition, db_path: Optional[str] = None) -> Dict[str, str]:
    whitelist = auto_def.permission_policy.secrets_whitelist or []
    auto_settings = auto_def.settings if isinstance(auto_def.settings, dict) else {}
    secrets_map: Dict[str, str] = {}

    try:
        account_overrides = auto_settings.get("integrations", {})
        for integration in get_integration_manager(db_path=db_path).list_integrations(decrypt=True):
            service_type = integration.get("service_type")
            if service_type in account_overrides and integration.get("id") != account_overrides[service_type]:
                continue
            for key, value in integration.get("secrets", {}).items():
                if not whitelist or key in whitelist or "*" in whitelist:
                    secrets_map[key] = str(value)
    except Exception as e:
        logger.warning(f"Errore recupero secrets da integrazioni: {e}")

    if isinstance(auto_settings.get("secrets"), dict):
        secrets_map.update({key: str(value) for key, value in auto_settings["secrets"].items()})

    for name in whitelist:
        if name != "*" and name not in secrets_map and name in os.environ:
            secrets_map[name] = os.environ[name]
    return secrets_map
