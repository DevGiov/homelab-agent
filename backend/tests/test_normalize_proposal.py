"""Caratterizzazione di `AutomationDefinition.normalize_proposal`.

Fissa il comportamento attuale del validatore tollerante (payload grezzi scritti da un LLM o dalla UI), così che
possa essere diviso in passi senza cambiarlo. Ogni caso confronta il dict normalizzato per intero e l'esito della
validazione del modello. Dove il comportamento sembra un difetto il caso lo fissa comunque ed è marcato
`# Da rivedere`: correggerlo è una decisione separata.

Valori generati resi deterministici: `uuid.uuid4` (id dell'automazione) e `secrets.token_urlsafe` (token webhook).
L'ordine di `allowed_tools` deriva da un set, quindi viene confrontato ordinato.
"""
import copy
import json
import logging
import secrets
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.automations import models
from app.automations.models import (
    AutomationDefinition,
    Budget,
    ExecutionPolicy,
    NotificationPolicy,
    Trigger,
    WorkflowSpec,
    WorkflowStepDefinition,
)

ABSENT = object()  # nel payload: chiave tolta; nell'atteso: chiave che non deve esserci

GEN_ID = "auto_01234567"
TOKEN = "tok24"  # secrets.token_urlsafe(24) sostituito dalla fixture
BUDGET = {
    "max_duration_seconds": 300,
    "max_llm_calls": 10,
    "max_tool_calls": 25,
    "max_tokens": 50000,
    "max_cost_usd": 0.0,
    "max_retries_per_step": 2,
}
NOTIFY = {
    "on_success": False,
    "on_failure": True,
    "on_approval_needed": True,
    "channels": ["ui_inbox"],
    "destination_webhook": None,
}
# Da rivedere: il default del validatore non ha "calendar", quello di ExecutionPolicy sì
REGISTRIES = ["mcp", "web", "code", "memory", "vision", "email", "automations"]
MANUAL = [{"id": "trg_manual", "type": "manual", "enabled": True}]
TEMPLATES_DIR = Path(models.__file__).parent / "templates"


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("0123456789abcdef0123456789abcdef"))
    monkeypatch.setattr(secrets, "token_urlsafe", lambda nbytes=None: f"tok{nbytes}")


# --- Costruttori di payload e risultati attesi ---

def st(step_id, name=None, *, type="deterministic_action", aot=None, params=None, prompt=None, **raw):
    """Step normalizzato: le chiavi che il validatore imposta sempre, più quelle grezze che passano invariate."""
    return {
        "step_id": step_id,
        "name": name or step_id,
        "type": type,
        "action_or_tool": aot,
        "parameters": params if params is not None else {},
        "prompt_template": prompt,
        **raw,
    }


def cron(expr, trigger_id="trg_1", **raw):
    return {"id": trigger_id, "type": "cron", "cron_expression": expr, "timezone": "Europe/Rome", "enabled": True,
            **raw}


def manual(trigger_id="trg_1", **raw):
    return {"id": trigger_id, "type": "manual", "timezone": "Europe/Rome", "enabled": True, **raw}


def webhook(path, token=TOKEN, trigger_id="trg_1", **raw):
    return {"id": trigger_id, "type": "webhook", "webhook_token": token, "webhook_path": path,
            "timezone": "Europe/Rome", "enabled": True, **raw}


def pp(*tools, registries=REGISTRIES, **raw):
    return {"allowed_tools": sorted(tools), "allowed_registries": list(registries), **raw}


BASE_STEP_RAW = {"step_id": "s1", "name": "S1", "type": "deterministic_action", "action_or_tool": "noop"}
BASE_WF = {"initial_step_id": "s1", "steps": [st("s1", "S1", aot="noop")]}
DEFAULTS = {
    "parameters": {},
    "settings": {},
    "workflow": BASE_WF,
    "triggers": MANUAL,
    "budget": BUDGET,
    "permission_policy": pp("noop"),
    "notification_policy": NOTIFY,
}


def P(**keys):
    """Payload base valido (un solo step deterministico, nessun trigger) con le chiavi date; ABSENT toglie la chiave."""
    payload = {"id": "auto_t", "name": "Prova", "workflow": {"initial_step_id": "s1", "steps": [dict(BASE_STEP_RAW)]}}
    payload.update(keys)
    return {k: v for k, v in payload.items() if v is not ABSENT}


def W(*steps, initial="s1", **keys):
    """Payload base con il workflow dato come dict."""
    return P(workflow={"initial_step_id": initial, "steps": list(steps)}, **keys)


def _canon(result):
    """Ordina allowed_tools, che il validatore costruisce da un set."""
    if isinstance(result, dict) and isinstance(result.get("permission_policy"), dict):
        tools = result["permission_policy"].get("allowed_tools")
        if isinstance(tools, list):
            result["permission_policy"]["allowed_tools"] = sorted(tools, key=repr)
    return result


def _expected(payload, overrides):
    exp = copy.deepcopy(payload)
    exp.update(copy.deepcopy(DEFAULTS))
    for key, value in overrides.items():
        if value is ABSENT:
            exp.pop(key, None)
        else:
            exp[key] = copy.deepcopy(value)
    return _canon(exp)


def normalize(payload):
    return _canon(AutomationDefinition.normalize_proposal(copy.deepcopy(payload)))


def _check_validation(payload, invalid):
    if invalid:
        with pytest.raises(ValidationError) as err:
            AutomationDefinition.model_validate(copy.deepcopy(payload))
        assert {tuple(e["loc"]) for e in err.value.errors()} == set(invalid)
    else:
        AutomationDefinition.model_validate(copy.deepcopy(payload))


def C(case_id, payload, *, invalid=(), raises=None, **expect):
    """Un caso: payload, sezioni attese diverse dai DEFAULTS, posizioni degli errori di validazione o eccezione grezza."""
    return pytest.param(payload, expect, invalid, raises, id=case_id)


# --- Corpus: sezioni di primo livello ---

CASES = [
    C("minimo", P()),

    # Identità e nome
    C("id_e_name_mancanti", P(id=ABSENT, name=ABSENT), id=GEN_ID, name=GEN_ID),
    C("id_vuoto_generato", P(id=""), id=GEN_ID),
    C("id_e_name_None", P(id=None, name=None), id=GEN_ID, name=GEN_ID),
    C("id_zero_generato", P(id=0), id=GEN_ID),
    C("name_vuoto_usa_id", P(name=""), name="auto_t"),

    # Parametri e settings
    C("parameters", P(parameters={"a": 1}), parameters={"a": 1}),
    C("params", P(params={"b": 2}), parameters={"b": 2}),
    C("inputs", P(inputs={"c": 3}), parameters={"c": 3}),
    C("config", P(config={"d": 4}), parameters={"d": 4}),
    C("parameters_vince_su_params", P(parameters={"a": 1}, params={"b": 2}), parameters={"a": 1}),
    C("parameters_vuoto_passa_a_params", P(parameters={}, params={"b": 2}), parameters={"b": 2}),
    C("parameters_None_passa_a_inputs", P(parameters=None, inputs={"c": 3}), parameters={"c": 3}),
    C("alias_vuoti_fino_a_config", P(params={}, inputs={}, config={"d": 4}), parameters={"d": 4}),
    C("parameters_lista", P(parameters=[1, 2]), parameters={}),
    C("parameters_stringa", P(parameters="a=1"), parameters={}),
    # Da rivedere: un valore non dict ma "vero" blocca gli alias validi che seguono
    C("parameters_lista_blocca_params", P(parameters=[1], params={"b": 2}), parameters={}),
    C("settings", P(settings={"s": 1}), settings={"s": 1}),
    C("custom_settings", P(custom_settings={"k": "v"}), settings={"k": "v"}),
    C("settings_vuoto_passa_a_custom", P(settings={}, custom_settings={"k": 1}), settings={"k": 1}),
    C("settings_stringa", P(settings="x"), settings={}),

    # Forma del workflow
    C("workflow_lista", P(workflow=[{"step_id": "a", "action": "x1"}, {"id": "b"}]),
      workflow={"initial_step_id": "a", "steps": [st("a", aot="x1", action="x1"), st("b", id="b")]},
      permission_policy=pp("x1")),
    C("workflow_lista_initial_da_id", P(workflow=[{"id": "b"}]),
      workflow={"initial_step_id": "b", "steps": [st("b", id="b")]}, permission_policy=pp()),
    C("workflow_lista_initial_default", P(workflow=[{"name": "A"}]),
      workflow={"initial_step_id": "step_1", "steps": [st("step_1", "A")]}, permission_policy=pp()),
    # Da rivedere: initial_step_id "step_1" punta a uno step che non esiste (il primo è scartato, il secondo è step_2)
    C("workflow_lista_primo_non_dict", P(workflow=["junk", {"name": "A"}]),
      workflow={"initial_step_id": "step_1", "steps": [st("step_2", "A")]}, permission_policy=pp()),
    # Da rivedere: un workflow senza step è valido
    C("workflow_lista_vuota", P(workflow=[]),
      workflow={"initial_step_id": "step_1", "steps": []}, permission_policy=pp()),
    C("workflow_lista_ignora_steps_top_level", P(workflow=[{"step_id": "a"}], steps=[{"step_id": "z"}]),
      workflow={"initial_step_id": "a", "steps": [st("a")]}, permission_policy=pp()),
    C("workflow_dict_initial_da_step_id", P(workflow={"steps": [{"step_id": "x"}]}),
      workflow={"initial_step_id": "x", "steps": [st("x")]}, permission_policy=pp()),
    C("workflow_dict_initial_da_id", P(workflow={"steps": [{"id": "y"}]}),
      workflow={"initial_step_id": "y", "steps": [st("y", id="y")]}, permission_policy=pp()),
    C("workflow_dict_initial_default", P(workflow={"steps": [{}]}),
      workflow={"initial_step_id": "step_1", "steps": [st("step_1")]}, permission_policy=pp()),
    C("workflow_dict_initial_vuoto", P(workflow={"initial_step_id": "", "steps": [{"step_id": "x"}]}),
      workflow={"initial_step_id": "x", "steps": [st("x")]}, permission_policy=pp()),
    C("workflow_dict_initial_diverso_dal_primo", P(workflow={"initial_step_id": "zz", "steps": [{"step_id": "a"}]}),
      workflow={"initial_step_id": "zz", "steps": [st("a")]}, permission_policy=pp()),
    C("workflow_dict_primo_non_dict", P(workflow={"steps": ["junk"]}),
      workflow={"steps": []}, permission_policy=pp(), invalid=[("workflow", "initial_step_id")]),
    C("workflow_dict_steps_vuoti", P(workflow={"steps": []}),
      workflow={"steps": []}, permission_policy=pp(), invalid=[("workflow", "initial_step_id")]),
    C("workflow_dict_senza_steps", P(workflow={"initial_step_id": "s1"}),
      workflow={"initial_step_id": "s1"}, permission_policy=pp(), invalid=[("workflow", "steps")]),
    C("workflow_dict_chiavi_extra",
      P(workflow={"initial_step_id": "s1", "steps": [dict(BASE_STEP_RAW)], "output_schema": {"type": "object"}}),
      workflow={**BASE_WF, "output_schema": {"type": "object"}}),
    C("workflow_dict_steps_dict_due_chiavi", P(workflow={"initial_step_id": "s1", "steps": {"a": 1, "b": 2}}),
      workflow={"initial_step_id": "s1", "steps": []}, permission_policy=pp()),
    C("steps_top_level", P(workflow=ABSENT, steps=[{"step_id": "a"}]),
      workflow={"initial_step_id": "a", "steps": [st("a")]}, steps=ABSENT, permission_policy=pp()),
    C("steps_top_level_workflow_None", P(workflow=None, steps=[{"id": "b"}]),
      workflow={"initial_step_id": "b", "steps": [st("b", id="b")]}, steps=ABSENT, permission_policy=pp()),
    C("steps_top_level_workflow_stringa_vuota", P(workflow="", steps=[{}]),
      workflow={"initial_step_id": "step_1", "steps": [st("step_1")]}, steps=ABSENT, permission_policy=pp()),
    C("steps_top_level_primo_non_dict", P(workflow=ABSENT, steps=["junk", {"name": "A"}]),
      workflow={"initial_step_id": "step_1", "steps": [st("step_2", "A")]}, steps=ABSENT, permission_policy=pp()),
    C("steps_top_level_tupla", P(workflow=ABSENT, steps=({"step_id": "a"},)),
      workflow={"initial_step_id": "a", "steps": [st("a")]}, steps=ABSENT, permission_policy=pp()),
    # Da rivedere: gli step dati come dict diventano le loro chiavi (stringhe), poi scartate: workflow vuoto e valido
    C("steps_top_level_dict", P(workflow=ABSENT, steps={"a": {"step_id": "a"}}),
      workflow={"initial_step_id": "step_1", "steps": []}, steps=ABSENT, permission_policy=pp()),
    # Da rivedere: un workflow {} vuoto nasconde gli step di primo livello
    C("workflow_dict_vuoto_ignora_steps_top_level", P(workflow={}, steps=[{"step_id": "a"}]),
      workflow={}, permission_policy=pp(), invalid=[("workflow", "initial_step_id"), ("workflow", "steps")]),
    C("workflow_assente", P(workflow=ABSENT), workflow=ABSENT, permission_policy=pp(), invalid=[("workflow",)]),
    C("workflow_None", P(workflow=None), workflow=None, permission_policy=pp(), invalid=[("workflow",)]),
    C("workflow_stringa", P(workflow="fai qualcosa"), workflow="fai qualcosa", permission_policy=pp(),
      invalid=[("workflow",)]),

    # Forme che oggi sollevano un'eccezione grezza invece di un errore di validazione (Da rivedere)
    C("steps_top_level_None", P(workflow=ABSENT, steps=None), raises=TypeError),
    C("workflow_steps_int", P(workflow={"steps": 5}), raises=TypeError),
    C("workflow_steps_dict_senza_initial", P(workflow={"steps": {"a": 1}}), raises=KeyError),
    C("workflow_initial_e_steps_None", P(workflow={"initial_step_id": "s1", "steps": None}), raises=TypeError),
    C("workflow_initial_e_steps_dict_una_chiave", P(workflow={"initial_step_id": "s1", "steps": {"a": 1}}),
      raises=KeyError),

    # Trigger: forme del campo
    C("trigger_dict", P(triggers={"type": "cron", "schedule": "0 12 * * *"}),
      triggers=[cron("0 12 * * *", schedule="0 12 * * *")]),
    C("trigger_stringa_cron", P(triggers="0 9 * * 1-5"), triggers=[cron("0 9 * * 1-5")]),
    C("trigger_stringa_con_spazi", P(triggers="  */5 * * * *  "), triggers=[cron("*/5 * * * *")]),
    # Da rivedere: una stringa senza cifre né asterischi diventa manuale, anche "@daily" o "webhook"
    C("trigger_stringa_senza_cifre", P(triggers="@daily"), triggers=[manual()]),
    C("trigger_stringa_webhook", P(triggers="webhook"), triggers=[manual()]),
    # Da rivedere: qualunque testo con una cifra diventa l'espressione cron, senza verifica
    C("trigger_stringa_testo_con_cifre", P(triggers="every 5 minutes"), triggers=[cron("every 5 minutes")]),
    # Da rivedere: triggers "" è una stringa, quindi il cron di primo livello è ignorato
    C("trigger_stringa_vuota_ignora_cron_top_level", P(triggers="", cron="5 * * * *"), triggers=[manual()]),
    C("cron_top_level", P(cron="5 * * * *"), triggers=[cron("5 * * * *")]),
    C("schedule_top_level_triggers_None", P(triggers=None, schedule="0 6 * * *"), triggers=[cron("0 6 * * *")]),
    C("cron_expression_top_level_triggers_vuoti", P(triggers=[], cron_expression=" 0 7 * * * "),
      triggers=[cron("0 7 * * *")]),
    C("cron_top_level_precedenza", P(cron="1 * * * *", schedule="2 * * * *", cron_expression="3 * * * *"),
      triggers=[cron("3 * * * *")]),
    C("cron_top_level_schedule_prima_di_cron", P(cron="1 * * * *", schedule="2 * * * *"),
      triggers=[cron("2 * * * *")]),
    C("cron_top_level_numero", P(cron=5), triggers=[cron("5")]),
    C("cron_top_level_ignorato_con_triggers", P(triggers=[{"type": "manual"}], cron="5 * * * *"),
      triggers=[manual()]),
    C("trigger_int", P(triggers=7), triggers=MANUAL),
    # Da rivedere: una tupla di trigger viene scartata per intero
    C("trigger_tupla", P(triggers=({"type": "cron", "cron_expression": "1 2 * * *"},)), triggers=MANUAL),
    C("trigger_lista_vuota", P(triggers=[]), triggers=MANUAL),
    C("trigger_lista_non_dict_saltati", P(triggers=["cron", None, {"type": "manual"}]), triggers=[manual("trg_3")]),
    C("trigger_lista_solo_stringhe", P(triggers=["0 9 * * *"]), triggers=MANUAL),
    C("trigger_id_dato", P(triggers=[{"id": "mio", "type": "manual"}]), triggers=[manual("mio")]),

    # Trigger: espressione cron e tipo
    C("trigger_cron_senza_tipo", P(triggers=[{"cron": "1 * * * *"}]), triggers=[cron("1 * * * *", cron="1 * * * *")]),
    C("trigger_cron_expr", P(triggers=[{"type": "cron", "cron_expr": "2 * * * *"}]),
      triggers=[cron("2 * * * *", cron_expr="2 * * * *")]),
    C("trigger_expression_con_spazi", P(triggers=[{"type": "cron", "expression": " 3 * * * * "}]),
      triggers=[cron("3 * * * *", expression=" 3 * * * * ")]),
    C("trigger_sinonimi_precedenza",
      P(triggers=[{"cron_expression": "a", "schedule": "b", "cron": "c", "cron_expr": "d", "expression": "e"}]),
      triggers=[cron("a", schedule="b", cron="c", cron_expr="d", expression="e")]),
    C("trigger_cron_numero", P(triggers=[{"type": "cron", "cron": 5}]), triggers=[cron("5", cron=5)]),
    C("trigger_vuoto", P(triggers=[{}]), triggers=[manual()]),
    C("trigger_tipo_non_valido_con_espressione", P(triggers=[{"type": "daily", "cron_expression": "0 6 * * *"}]),
      triggers=[cron("0 6 * * *")]),
    C("trigger_tipo_non_valido", P(triggers=[{"type": "daily"}]), triggers=[manual()]),
    C("trigger_tipo_None", P(triggers=[{"type": None}]), triggers=[manual()]),
    C("trigger_tipo_maiuscolo", P(triggers=[{"type": "CRON", "cron_expression": "0 6 * * *"}]),
      triggers=[cron("0 6 * * *")]),
    C("trigger_cron_senza_espressione", P(triggers=[{"type": "cron"}]), triggers=[cron("0 9 * * *")]),
    C("trigger_manual_con_espressione", P(triggers=[{"type": "manual", "cron_expression": "0 6 * * *"}]),
      triggers=[cron("0 6 * * *")]),
    C("trigger_webhook", P(triggers=[{"type": "webhook"}]),
      triggers=[webhook(f"/v1/automations/auto_t/webhook/{TOKEN}")]),
    C("trigger_webhook_token_dato", P(triggers=[{"type": "Webhook", "webhook_token": "abc"}]),
      triggers=[webhook("/v1/automations/auto_t/webhook/abc", token="abc")]),
    C("trigger_webhook_path_dato", P(triggers=[{"type": "webhook", "webhook_path": "/hook"}]),
      triggers=[webhook("/hook")]),
    C("trigger_webhook_con_espressione", P(triggers=[{"type": "webhook", "cron_expression": "0 6 * * *"}]),
      triggers=[webhook(f"/v1/automations/auto_t/webhook/{TOKEN}", cron_expression="0 6 * * *")]),
    C("trigger_webhook_id_generato", P(id=ABSENT, triggers=[{"type": "webhook"}]),
      id=GEN_ID, triggers=[webhook(f"/v1/automations/{GEN_ID}/webhook/{TOKEN}")]),
    C("trigger_event", P(triggers=[{"type": "event", "event_pattern": {"source": "mail"}}]),
      triggers=[{"id": "trg_1", "type": "event", "event_pattern": {"source": "mail"}, "timezone": "Europe/Rome",
                 "enabled": True}]),
    C("trigger_timezone_vuota", P(triggers=[{"type": "manual", "timezone": ""}]), triggers=[manual()]),
    C("trigger_timezone_data", P(triggers=[{"type": "manual", "timezone": "UTC"}]),
      triggers=[{**manual(), "timezone": "UTC"}]),
    C("trigger_disabilitato", P(triggers=[{"type": "manual", "enabled": False}]),
      triggers=[{**manual(), "enabled": False}]),
    C("trigger_enabled_None", P(triggers=[{"type": "manual", "enabled": None}]),
      triggers=[{**manual(), "enabled": None}], invalid=[("triggers", 0, "enabled")]),

    # Trigger cron dedotto da name/description quando non c'è un cron esplicito
    C("inferenza_mezzogiorno", P(description="Ogni giorno a mezzogiorno"), triggers=[cron("0 12 * * *")]),
    C("inferenza_alle_12", P(name="Report alle 12"), triggers=[cron("0 12 * * *")]),
    C("inferenza_ore_12", P(description="alle ore 12 in punto"), triggers=[cron("0 12 * * *")]),
    C("inferenza_alle_10", P(name="Report alle 10"), triggers=[cron("0 10 * * *")]),
    C("inferenza_ore_10", P(description="ore 10"), triggers=[cron("0 10 * * *")]),
    C("inferenza_alle_9", P(description="alle 9"), triggers=[cron("0 9 * * *")]),
    C("inferenza_ore_9", P(description="ore 9"), triggers=[cron("0 9 * * *")]),
    C("inferenza_alle_09", P(description="alle 09"), triggers=[cron("0 9 * * *")]),
    C("inferenza_alle_8", P(description="alle 8"), triggers=[cron("0 8 * * *")]),
    C("inferenza_ore_8", P(description="ore 8"), triggers=[cron("0 8 * * *")]),
    C("inferenza_alle_08", P(description="alle 08"), triggers=[cron("0 8 * * *")]),
    C("inferenza_ogni_ora", P(description="Controlla ogni ora"), triggers=[cron("0 * * * *")]),
    C("inferenza_hourly", P(name="Hourly check"), triggers=[cron("0 * * * *")]),
    C("inferenza_orario_alle", P(description="alle 18:30"), triggers=[cron("30 18 * * *")]),
    C("inferenza_orario_ore_punto", P(description="ore 7.05"), triggers=[cron("5 7 * * *")]),
    C("inferenza_orario_at", P(description="at 23:59"), triggers=[cron("59 23 * * *")]),
    C("inferenza_maiuscole", P(name="REPORT ALLE 10"), triggers=[cron("0 10 * * *")]),
    C("inferenza_precedenza_mezzogiorno", P(description="a mezzogiorno e alle 10"), triggers=[cron("0 12 * * *")]),
    C("inferenza_da_id_senza_name", P(id="report ore 10", name=ABSENT),
      name="report ore 10", triggers=[cron("0 10 * * *")]),
    # Da rivedere: "alle 9:30" passa dal controllo "alle 9" prima della regex e perde i minuti
    C("inferenza_alle_9_30_perde_minuti", P(description="alle 9:30"), triggers=[cron("0 9 * * *")]),
    # Da rivedere: l'ora non è verificata, ne esce un cron non valido
    C("inferenza_ora_fuori_range", P(description="at 25:00"), triggers=[cron("0 25 * * *")]),
    # Da rivedere: falsi positivi su sottostringhe ("format 3.14" contiene "at 3.14", "sensore 12" contiene "ore 12")
    C("inferenza_falso_positivo_at", P(description="Converti il format 3.14"), triggers=[cron("14 3 * * *")]),
    C("inferenza_falso_positivo_ore", P(description="Leggi il sensore 12"), triggers=[cron("0 12 * * *")]),
    C("inferenza_aggiunta_a_manual", P(name="Report alle 10", triggers=[{"type": "manual"}]),
      triggers=[manual(), cron("0 10 * * *", "trg_2")]),
    C("inferenza_aggiunta_a_stringa", P(name="Report ogni ora", triggers="@daily"),
      triggers=[manual(), cron("0 * * * *", "trg_2")]),
    C("inferenza_sostituisce_int", P(name="Report ogni ora", triggers=7), triggers=[cron("0 * * * *")]),
    C("inferenza_no_con_cron_esplicito", P(name="Report alle 10", triggers=[{"type": "cron", "cron_expression": "5 4 * * *"}]),
      triggers=[cron("5 4 * * *")]),
    C("inferenza_no_con_cron_expression_su_manual",
      P(name="Report alle 10", triggers=[{"type": "manual", "cron_expression": "5 4 * * *"}]),
      triggers=[cron("5 4 * * *")]),
    C("inferenza_no_con_schedule", P(name="Report alle 10", triggers=[{"schedule": "5 4 * * *"}]),
      triggers=[cron("5 4 * * *", schedule="5 4 * * *")]),
    C("inferenza_no_con_cron_top_level", P(name="Report alle 10", cron="5 4 * * *"), triggers=[cron("5 4 * * *")]),
    # Da rivedere: cron_expr ed expression non contano come cron esplicito, quindi si aggiunge un secondo cron
    C("inferenza_con_cron_expr", P(name="Report alle 10", triggers=[{"cron_expr": "5 4 * * *"}]),
      triggers=[cron("5 4 * * *", cron_expr="5 4 * * *"), cron("0 10 * * *", "trg_2")]),
    # Da rivedere: type "CRON" non conta come cron esplicito; diventa cron "0 9" e se ne aggiunge un secondo
    C("inferenza_con_tipo_maiuscolo", P(name="Report alle 10", triggers=[{"type": "CRON"}]),
      triggers=[cron("0 9 * * *"), cron("0 10 * * *", "trg_2")]),
    C("description_None", P(description=None), invalid=[("description",)]),

    # Budget
    C("budget_None", P(budget=None)),
    C("budget_stringa", P(budget="alto")),
    C("budget_lista", P(budget=[1])),
    C("budget_vuoto", P(budget={})),
    C("budget_parziale", P(budget={"max_llm_calls": 3}), budget={**BUDGET, "max_llm_calls": 3}),
    C("budget_max_tokens_per_run", P(budget={"max_tokens_per_run": 999}),
      budget={**BUDGET, "max_tokens": 999, "max_tokens_per_run": 999}),
    C("budget_max_tokens_vince", P(budget={"max_tokens": 5, "max_tokens_per_run": 999}),
      budget={**BUDGET, "max_tokens": 5, "max_tokens_per_run": 999}),
    C("budget_timeout_seconds", P(budget={"timeout_seconds": 60}),
      budget={**BUDGET, "max_duration_seconds": 60, "timeout_seconds": 60}),
    C("budget_duration_seconds", P(budget={"duration_seconds": 70}),
      budget={**BUDGET, "max_duration_seconds": 70, "duration_seconds": 70}),
    C("budget_timeout_prima_di_duration", P(budget={"timeout_seconds": 60, "duration_seconds": 70}),
      budget={**BUDGET, "max_duration_seconds": 60, "timeout_seconds": 60, "duration_seconds": 70}),
    C("budget_max_duration_vince", P(budget={"max_duration_seconds": 10, "timeout_seconds": 60}),
      budget={**BUDGET, "max_duration_seconds": 10, "timeout_seconds": 60}),
    C("budget_None_scartati", P(budget={"max_llm_calls": None, "max_tokens_per_run": None})),
    C("budget_chiavi_extra", P(budget={"foo": 1}), budget={**BUDGET, "foo": 1}),
    C("budget_negativo", P(budget={"max_llm_calls": -1}), budget={**BUDGET, "max_llm_calls": -1},
      invalid=[("budget", "max_llm_calls")]),

    # Permission policy
    C("policy_None", P(permission_policy=None)),
    C("policy_stringa_safest", P(permission_policy="SAFEST"), permission_policy=pp("noop", security_mode="safest")),
    C("policy_stringa_dangerous", P(permission_policy="dangerous"),
      permission_policy=pp("noop", security_mode="dangerous")),
    C("policy_stringa_normal", P(permission_policy="normal"), permission_policy=pp("noop", security_mode="normal")),
    C("policy_stringa_sconosciuta", P(permission_policy="auto_execute"),
      permission_policy=pp("noop", security_mode="normal")),
    C("policy_stringa_con_spazi", P(permission_policy=" safest"), permission_policy=pp("noop", security_mode="normal")),
    C("policy_int", P(permission_policy=5)),
    C("policy_lista", P(permission_policy=["web"])),
    C("policy_tools_vuoti_dedotti_dagli_step",
      W({"step_id": "a", "action": "curl"}, {"step_id": "b", "action_or_tool": "http_get"}, {"step_id": "c"},
        {"step_id": "d", "tool": "custom"}, initial="a", permission_policy={"allowed_tools": []}),
      workflow={"initial_step_id": "a", "steps": [st("a", aot="http_get", action="curl"), st("b", aot="http_get"),
                                                    st("c"), st("d", aot="custom", tool="custom")]},
      permission_policy=pp("custom", "http_get")),
    C("policy_tools_None_dedotti", P(permission_policy={"allowed_tools": None})),
    C("policy_tools_espliciti_con_alias",
      P(permission_policy={"allowed_tools": ["curl", "Save-File", "Brave-Search", "custom", "custom"]}),
      permission_policy=pp("curl", "http_get", "Save-File", "save_artifact", "Brave-Search", "web_search", "custom")),
    C("policy_tools_canonici", P(permission_policy={"allowed_tools": ["http_get", "save_artifact", "web_search"]}),
      permission_policy=pp("http_get", "save_artifact", "web_search")),
    # Da rivedere: una stringa viene scorsa carattere per carattere
    C("policy_tools_stringa", P(permission_policy={"allowed_tools": "curl"}), permission_policy=pp("c", "u", "r", "l")),
    C("policy_registries_vuote", P(permission_policy={"allowed_registries": []})),
    C("policy_registries_None", P(permission_policy={"allowed_registries": None})),
    C("policy_registries_date", P(permission_policy={"allowed_registries": ["web"]}),
      permission_policy=pp("noop", registries=["web"])),
    C("policy_chiavi_passano",
      P(permission_policy={"security_mode": "safest", "allowed_hosts": ["example.com"], "secrets_whitelist": ["K"]}),
      permission_policy=pp("noop", security_mode="safest", allowed_hosts=["example.com"], secrets_whitelist=["K"])),

    # Notification policy
    C("notifiche_None", P(notification_policy=None)),
    C("notifiche_stringa", P(notification_policy="email")),
    C("notifiche_vuote", P(notification_policy={})),
    C("notifiche_parziali", P(notification_policy={"on_success": True}),
      notification_policy={**NOTIFY, "on_success": True}),
    C("notifiche_None_scartati",
      P(notification_policy={"channels": None, "destination_webhook": None, "on_failure": False}),
      notification_policy={**NOTIFY, "on_failure": False}),
    C("notifiche_chiavi_extra", P(notification_policy={"email": "a@example.com"}),
      notification_policy={**NOTIFY, "email": "a@example.com"}),

    # Chiavi che il validatore non tocca
    C("chiavi_top_level_passano",
      P(description="d", version=3, enabled=False, retention_days=7, model="loaded", created_by="agent",
        source_type="agent", input_schema={"type": "object"}, extra_key="x")),
]


@pytest.mark.parametrize("payload, expect, invalid, raises", CASES)
def test_payload(payload, expect, invalid, raises):
    if raises:
        with pytest.raises(raises):
            AutomationDefinition.normalize_proposal(copy.deepcopy(payload))
        with pytest.raises(raises):
            AutomationDefinition.model_validate(copy.deepcopy(payload))
        return
    assert normalize(payload) == _expected(payload, expect)
    _check_validation(payload, invalid)


# --- Corpus: step del workflow ---

def S(case_id, raw_steps, expected_steps, *, invalid=()):
    return pytest.param(raw_steps, expected_steps, invalid, id=case_id)


_HTTP_ALIASES = ["http_get", "curl", "fetch_url", "web_fetch", "fetch_web", "HTTP-GET", "Fetch-Url"]
_SAVE_ALIASES = ["file_write", "write_file", "save_file", "save_report", "save_artifact", "save_briefing_artifact",
                 "Save-Report"]
_SEARCH_ALIASES = ["web_search", "search", "google", "brave_search", "Brave-Search"]

STEP_CASES = [
    # Identità e nome dello step
    S("step_id_da_id", [{"id": "a", "name": "A"}], [st("a", "A", id="a")]),
    S("step_id_vuoto_usa_id", [{"step_id": "", "id": "b", "name": "B"}], [st("b", "B", id="b")]),
    S("step_id_da_indice", [{"name": "A"}, {"name": "B"}], [st("step_1", "A"), st("step_2", "B")]),
    S("indice_conta_gli_scartati", ["junk", None, 3, {"name": "C"}], [st("step_4", "C")]),
    S("name_da_title", [{"step_id": "a", "title": "Titolo"}], [st("a", "Titolo", title="Titolo")]),
    S("name_vuoto_usa_title", [{"step_id": "a", "name": "", "title": "T"}], [st("a", "T", title="T")]),
    S("name_da_step_id", [{"step_id": "a"}], [st("a", "a")]),
    S("step_vuoto", [{}], [st("step_1")]),

    # Azione o tool
    S("action", [{"step_id": "a", "action": "do_x"}], [st("a", aot="do_x", action="do_x")]),
    S("tool", [{"step_id": "a", "tool": "do_y"}], [st("a", aot="do_y", tool="do_y")]),
    S("action_prima_di_tool", [{"step_id": "a", "action": "do_x", "tool": "do_y"}],
      [st("a", aot="do_x", action="do_x", tool="do_y")]),
    S("action_or_tool_vuoto_usa_action", [{"step_id": "a", "action_or_tool": "", "action": "do_x"}],
      [st("a", aot="do_x", action="do_x")]),
    S("tool_sconosciuto_mantiene_maiuscole", [{"step_id": "a", "action_or_tool": "MyTool"}], [st("a", aot="MyTool")]),
    S("tool_quasi_alias_invariato", [{"step_id": "a", "action_or_tool": "web-search-pro"}],
      [st("a", aot="web-search-pro")]),
    S("alias_da_action", [{"step_id": "a", "action": "curl"}], [st("a", aot="http_get", action="curl")]),
    *[S(f"alias_http_{t}", [{"step_id": "a", "action_or_tool": t}], [st("a", aot="http_get")]) for t in _HTTP_ALIASES],
    *[S(f"alias_save_{t}", [{"step_id": "a", "action_or_tool": t}], [st("a", aot="save_artifact")])
      for t in _SAVE_ALIASES],
    *[S(f"alias_search_{t}", [{"step_id": "a", "action_or_tool": t}], [st("a", aot="web_search")])
      for t in _SEARCH_ALIASES],

    # Parametri dello step
    S("parametri", [{"step_id": "a", "parameters": {"p": 1}}], [st("a", params={"p": 1})]),
    S("parametri_da_arguments", [{"step_id": "a", "arguments": {"x": 1}}],
      [st("a", params={"x": 1}, arguments={"x": 1})]),
    S("parametri_da_args", [{"step_id": "a", "args": {"x": 2}}], [st("a", params={"x": 2}, args={"x": 2})]),
    S("parametri_da_params", [{"step_id": "a", "params": {"x": 3}}], [{**st("a", params={"x": 3}), "params": {"x": 3}}]),
    S("parametri_precedenza", [{"step_id": "a", "parameters": {"p": 1}, "arguments": {"x": 1}}],
      [st("a", params={"p": 1}, arguments={"x": 1})]),
    S("parametri_vuoti_passano_ad_args", [{"step_id": "a", "parameters": {}, "args": {"x": 1}}],
      [st("a", params={"x": 1}, args={"x": 1})]),
    S("parametri_stringa", [{"step_id": "a", "parameters": "q=1"}], [st("a")]),
    S("parametri_lista_blocca_args", [{"step_id": "a", "parameters": [1], "args": {"x": 1}}],
      [st("a", args={"x": 1})]),
    S("input_source", [{"step_id": "a", "input_source": "s0"}],
      [st("a", params={"input_source": "s0"}, input_source="s0")]),
    S("content_source", [{"step_id": "a", "content_source": "s0"}],
      [st("a", params={"content_source": "s0"}, content_source="s0")]),
    S("input_source_non_sovrascrive", [{"step_id": "a", "input_source": "top", "parameters": {"input_source": "in"}}],
      [st("a", params={"input_source": "in"}, input_source="top")]),
    S("content_source_non_sovrascrive",
      [{"step_id": "a", "content_source": "top", "parameters": {"content_source": "in"}}],
      [st("a", params={"content_source": "in"}, content_source="top")]),
    S("input_source_None_copiato", [{"step_id": "a", "input_source": None}],
      [st("a", params={"input_source": None}, input_source=None)]),
    S("filename_diventa_path", [{"step_id": "a", "parameters": {"filename": "r.md"}}],
      [st("a", params={"filename": "r.md", "path": "r.md"})]),
    S("path_non_sovrascritto", [{"step_id": "a", "parameters": {"filename": "a.md", "path": "b.md"}}],
      [st("a", params={"filename": "a.md", "path": "b.md"})]),
    S("filename_top_level_ignorato", [{"step_id": "a", "filename": "r.md"}], [st("a", filename="r.md")]),

    # Prompt
    S("prompt", [{"step_id": "a", "prompt": "Riassumi"}],
      [{**st("a", type="agentic_task", prompt="Riassumi"), "prompt": "Riassumi"}]),
    S("instruction", [{"step_id": "a", "instruction": "I"}],
      [st("a", type="agentic_task", prompt="I", instruction="I")]),
    S("task", [{"step_id": "a", "task": "T"}], [st("a", type="agentic_task", prompt="T", task="T")]),
    # Da rivedere: un tool deterministico con un parametro "prompt" e senza tipo diventa uno step agentico
    S("prompt_dai_parametri", [{"step_id": "a", "action_or_tool": "gen_image", "parameters": {"prompt": "P"}}],
      [st("a", type="agentic_task", aot="gen_image", params={"prompt": "P"}, prompt="P")]),
    S("prompt_precedenza", [{"step_id": "a", "prompt": "p", "instruction": "i", "task": "t"}],
      [{**st("a", type="agentic_task", prompt="p"), "prompt": "p", "instruction": "i", "task": "t"}]),
    S("prompt_template_vince", [{"step_id": "a", "prompt_template": "PT", "prompt": "p"}],
      [{**st("a", type="agentic_task", prompt="PT"), "prompt": "p"}]),
    S("prompt_template_vuoto_usa_task", [{"step_id": "a", "prompt_template": "", "task": "t"}],
      [st("a", type="agentic_task", prompt="t", task="t")]),

    # Tipo dello step
    *[S(f"tipo_valido_{t}", [{"step_id": "a", "type": t}], [st("a", type=t)])
      for t in ["deterministic_action", "agentic_task", "approval_gate", "evaluation_gate", "custom_code", "calendar"]],
    S("tipo_valido_maiuscolo", [{"step_id": "a", "type": "Custom_Code"}], [st("a", type="custom_code")]),
    *[S(f"tipo_agentico_{t}", [{"step_id": "a", "type": t}], [st("a", type="agentic_task")])
      for t in ["llm_call", "agent", "llm", "agent_task", "ai_task", "ai", "LLM"]],
    *[S(f"tipo_codice_{t}", [{"step_id": "a", "type": t}], [st("a", type="custom_code")])
      for t in ["code", "python", "Script"]],
    *[S(f"tipo_approvazione_{t}", [{"step_id": "a", "type": t}], [st("a", type="approval_gate")])
      for t in ["approval", "gate"]],
    S("tipo_sconosciuto", [{"step_id": "a", "type": "tool"}], [st("a")]),
    S("tipo_evaluation_non_alias", [{"step_id": "a", "type": "evaluation"}], [st("a")]),
    S("tipo_None", [{"step_id": "a", "type": None}], [st("a")]),
    S("tipo_numero", [{"step_id": "a", "type": 5}], [st("a")]),
    # Da rivedere: con un prompt, un tipo "python" o "gate" diventa agentico
    S("tipo_codice_con_prompt", [{"step_id": "a", "type": "python", "prompt": "p"}],
      [{**st("a", type="agentic_task", prompt="p"), "prompt": "p"}]),
    S("tipo_gate_con_prompt", [{"step_id": "a", "type": "gate", "task": "t"}],
      [st("a", type="agentic_task", prompt="t", task="t")]),
    S("tipo_valido_con_prompt_resta", [{"step_id": "a", "type": "deterministic_action", "task": "t"}],
      [st("a", prompt="t", task="t")]),
    S("tipo_approval_gate_con_prompt_resta", [{"step_id": "a", "type": "approval_gate", "task": "t"}],
      [st("a", type="approval_gate", prompt="t", task="t")]),

    # Timeout
    S("timeout_stringa", [{"step_id": "a", "timeout": "30"}], [st("a", timeout="30", timeout_seconds=30)]),
    S("timeout_float_troncato", [{"step_id": "a", "timeout": 12.9}], [st("a", timeout=12.9, timeout_seconds=12)]),
    S("timeout_seconds_vince", [{"step_id": "a", "timeout": 5, "timeout_seconds": 90}],
      [st("a", timeout=5, timeout_seconds=90)]),
    S("timeout_zero", [{"step_id": "a", "timeout": 0}], [st("a", timeout=0, timeout_seconds=0)],
      invalid=[("workflow", "steps", 0, "timeout_seconds")]),

    # Chiavi dello step che passano invariate
    S("chiavi_step_passano",
      [{"step_id": "a", "requires_approval": True, "condition": "x > 1", "on_failure_step_id": "b",
        "idempotency_key_template": "k", "tools": [], "timeout_seconds": 45}],
      [st("a", requires_approval=True, condition="x > 1", on_failure_step_id="b", idempotency_key_template="k",
          tools=[], timeout_seconds=45)]),

    # Espansione da template che NON scatta
    S("template_azione_troppo_corta", [{"step_id": "a", "action": "sync"}], [st("a", aot="sync", action="sync")]),
    S("template_non_sottostringa", [{"step_id": "a", "action": "daily_report"}],
      [st("a", aot="daily_report", action="daily_report")]),
    # Da rivedere: "tool" non è considerato per l'espansione, "action" e "action_or_tool" sì
    S("template_da_tool_ignorato", [{"step_id": "a", "tool": "github_issue_repair"}],
      [st("a", aot="github_issue_repair", tool="github_issue_repair")]),
    S("template_due_step", [{"step_id": "a", "action": "github_issue_repair"}, {"step_id": "b"}],
      [st("a", aot="github_issue_repair", action="github_issue_repair"), st("b")]),
]


@pytest.mark.parametrize("raw_steps, expected_steps, invalid", STEP_CASES)
def test_step(raw_steps, expected_steps, invalid):
    payload = W(*raw_steps)
    tools = {s["action_or_tool"] for s in expected_steps if s["action_or_tool"]}
    expected = _expected(payload, {"workflow": {"initial_step_id": "s1", "steps": expected_steps},
                                   "permission_policy": pp(*tools)})
    assert normalize(payload) == expected
    _check_validation(payload, invalid)


# --- Casi singoli ---

@pytest.mark.parametrize("value", ["testo", None, 5, [{"id": "a"}]])
def test_input_non_dict_restituito_invariato(value):
    assert AutomationDefinition.normalize_proposal(value) is value


def test_timeout_non_numerico_diventa_errore_di_validazione():
    payload = W({"step_id": "a", "timeout": "abc"})
    with pytest.raises(ValueError, match="invalid literal for int"):
        AutomationDefinition.normalize_proposal(copy.deepcopy(payload))
    with pytest.raises(ValidationError) as err:
        AutomationDefinition.model_validate(payload)
    assert [e["type"] for e in err.value.errors()] == ["value_error"]


def test_timeout_None_solleva_type_error():
    # Da rivedere: eccezione grezza invece di un errore di validazione
    payload = W({"step_id": "a", "timeout": None})
    with pytest.raises(TypeError):
        AutomationDefinition.normalize_proposal(copy.deepcopy(payload))
    with pytest.raises(TypeError):
        AutomationDefinition.model_validate(payload)


def test_payload_non_modificato():
    payload = {
        "name": "Ricca",
        "params": {"a": 1},
        "custom_settings": {"k": "v"},
        "steps": [{"title": "Cerca", "tool": "curl", "args": {"url": "https://example.com"}, "input_source": "x"},
                  {"action": "save-report", "parameters": {"filename": "r.md"}, "timeout": "30"}],
        "triggers": {"type": "webhook"},
        "budget": {"max_tokens_per_run": 10, "max_llm_calls": None},
        "permission_policy": {"allowed_tools": ["curl"]},
        "notification_policy": {"on_success": True, "channels": None},
    }
    before = copy.deepcopy(payload)
    AutomationDefinition.normalize_proposal(payload)
    assert payload == before


def test_inferenza_modifica_la_lista_trigger_del_chiamante():
    # Da rivedere: il trigger dedotto viene aggiunto alla lista del payload originale
    triggers = [{"type": "manual"}]
    payload = P(name="Report alle 10", triggers=triggers)
    result = AutomationDefinition.normalize_proposal(payload)
    assert triggers == [{"type": "manual"}, {"type": "cron", "cron_expression": "0 10 * * *", "timezone": "Europe/Rome"}]
    assert result["triggers"] == [manual(), cron("0 10 * * *", "trg_2")]


def test_inferenza_scrive_nel_log(caplog):
    with caplog.at_level(logging.INFO, logger="automations.models"):
        AutomationDefinition.normalize_proposal(P(name="Report alle 10"))
    records = [r for r in caplog.records if r.name == "automations.models"]
    assert [(r.levelno, r.getMessage()) for r in records] == [
        (logging.INFO, "Inferito trigger cron '0 10 * * *' per automazione 'auto_t' da testo descrittivo."),
    ]


def test_nessun_log_senza_inferenza(caplog):
    with caplog.at_level(logging.DEBUG, logger="automations.models"):
        AutomationDefinition.normalize_proposal(P())
    assert [r for r in caplog.records if r.name == "automations.models"] == []


def test_istanze_di_policy_e_budget_vengono_serializzate():
    payload = P(
        budget=Budget(max_llm_calls=3),
        permission_policy=ExecutionPolicy(allowed_tools=["curl"]),
        notification_policy=NotificationPolicy(on_success=True),
    )
    policy = ExecutionPolicy().model_dump()
    assert normalize(payload) == _expected(payload, {
        "budget": {**BUDGET, "max_llm_calls": 3},
        # Un'istanza conserva le sue allowed_registries (con "calendar")
        "permission_policy": {**policy, "allowed_tools": ["curl", "http_get"]},
        "notification_policy": {**NOTIFY, "on_success": True},
    })


def test_istanza_policy_senza_tools_li_deduce_dagli_step():
    payload = P(permission_policy=ExecutionPolicy())
    assert normalize(payload) == _expected(payload, {
        "permission_policy": {**ExecutionPolicy().model_dump(), "allowed_tools": ["noop"]},
    })


def test_istanze_di_trigger_e_step_vengono_scartate():
    # Da rivedere: i modelli Trigger e WorkflowStepDefinition non sono dict, quindi vengono saltati
    trigger = Trigger(id="t", type="cron", cron_expression="1 2 * * *")
    step = WorkflowStepDefinition(step_id="x", name="X", type="custom_code")
    payload = W(step, {"step_id": "b"}, triggers=[trigger])
    assert normalize(payload) == _expected(payload, {
        "workflow": {"initial_step_id": "s1", "steps": [st("b")]},
        "triggers": MANUAL,
        "permission_policy": pp(),
    })


def test_istanza_di_workflow_resta_com_e():
    spec = WorkflowSpec(initial_step_id="x", steps=[WorkflowStepDefinition(step_id="x", name="X", type="custom_code",
                                                                            action_or_tool="curl")])
    result = AutomationDefinition.normalize_proposal(P(workflow=spec))
    assert result["workflow"] is spec
    assert result["permission_policy"] == pp()


# --- Espansione da template di uno step singolo ---

def _template(name):
    return json.loads((TEMPLATES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("step, template", [
    ({"step_id": "a", "action_or_tool": "github_issue_repair"}, "github_issue_repair"),
    ({"step_id": "a", "action": "Daily-Email-Briefing"}, "daily_email_briefing"),
    ({"step_id": "a", "action": "run_email_to_calendar_sync_now"}, "email_to_calendar_sync"),
    # Da rivedere: basta una sottostringa di almeno 5 caratteri del nome del template
    ({"step_id": "a", "action": "repair"}, "github_issue_repair"),
    ({"step_id": "a", "action_or_tool": "briefing"}, "daily_email_briefing"),
])
def test_template_sostituisce_lo_step_singolo(step, template):
    tpl = _template(template)
    result = normalize(W(step))
    # Equivale a dare direttamente workflow e policy del template; parameters, trigger e budget del template no
    assert result == normalize(P(workflow=tpl["workflow"], permission_policy=tpl["permission_policy"]))
    assert result["workflow"]["initial_step_id"] == tpl["workflow"]["initial_step_id"]
    assert [s["step_id"] for s in result["workflow"]["steps"]] == [s["step_id"] for s in tpl["workflow"]["steps"]]


def test_template_anche_da_workflow_lista():
    tpl = _template("github_issue_repair")
    result = normalize(P(workflow=[{"action": "github-issue-repair"}]))
    assert result == normalize(P(workflow=tpl["workflow"], permission_policy=tpl["permission_policy"]))


def test_template_ambiguo_ne_sceglie_uno():
    # Da rivedere: "email" corrisponde a due template; vince il primo nell'ordine del filesystem
    result = normalize(W({"step_id": "a", "action": "email"}))
    candidates = [
        normalize(P(workflow=tpl["workflow"], permission_policy=tpl["permission_policy"]))
        for tpl in (_template("daily_email_briefing"), _template("email_to_calendar_sync"))
    ]
    assert result in candidates


def test_template_illeggibile_ignorato(monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("json rotto")

    monkeypatch.setattr(json, "load", broken)
    payload = W({"step_id": "a", "action_or_tool": "github_issue_repair"})
    assert normalize(payload) == _expected(payload, {
        "workflow": {"initial_step_id": "s1", "steps": [st("a", aot="github_issue_repair")]},
        "permission_policy": pp("github_issue_repair"),
    })


@pytest.mark.parametrize("fake", [{"name": "senza workflow"}, {"workflow": {"initial_step_id": "t1"}}])
def test_template_senza_steps_ignorato(monkeypatch, fake):
    monkeypatch.setattr(json, "load", lambda *a, **k: copy.deepcopy(fake))
    payload = W({"step_id": "a", "action_or_tool": "github_issue_repair"})
    assert normalize(payload) == _expected(payload, {
        "workflow": {"initial_step_id": "s1", "steps": [st("a", aot="github_issue_repair")]},
        "permission_policy": pp("github_issue_repair"),
    })


def test_template_senza_initial_ne_policy(monkeypatch):
    fake = {"workflow": {"steps": [{"step_id": "t1", "action": "curl"}]}}
    monkeypatch.setattr(json, "load", lambda *a, **k: copy.deepcopy(fake))
    payload = W({"step_id": "a", "action_or_tool": "github_issue_repair"}, permission_policy="safest")
    assert normalize(payload) == _expected(payload, {
        "workflow": {"initial_step_id": "step_1", "steps": [st("t1", aot="http_get", action="curl")]},
        "permission_policy": pp("http_get", security_mode="safest"),
    })


def test_template_policy_stringa(monkeypatch):
    fake = {"workflow": {"initial_step_id": "t1", "steps": [{"step_id": "t1"}]}, "permission_policy": "dangerous"}
    monkeypatch.setattr(json, "load", lambda *a, **k: copy.deepcopy(fake))
    payload = W({"step_id": "a", "action_or_tool": "github_issue_repair"}, permission_policy={"allowed_tools": ["x"]})
    assert normalize(payload) == _expected(payload, {
        "workflow": {"initial_step_id": "t1", "steps": [st("t1")]},
        "permission_policy": pp(security_mode="dangerous"),
    })


# --- Il modello risultante, per intero ---

def test_modello_da_payload_minimo():
    auto = AutomationDefinition.model_validate({"workflow": [{"prompt": "Riassumi le notizie"}]})
    dump = auto.model_dump(mode="json")
    assert dump == {
        "id": GEN_ID,
        "name": GEN_ID,
        "description": "",
        "version": 1,
        "enabled": True,
        "triggers": [{"id": "trg_manual", "type": "manual", "cron_expression": None, "timezone": "Europe/Rome",
                      "webhook_path": None, "webhook_secret_ref": None, "webhook_token": None,
                      "event_pattern": None, "enabled": True}],
        "workflow": {
            "initial_step_id": "step_1",
            "steps": [{"step_id": "step_1", "name": "step_1", "type": "agentic_task", "action_or_tool": None,
                       "prompt_template": "Riassumi le notizie", "tools": None, "parameters": {},
                       "requires_approval": False, "condition": None, "on_failure_step_id": None,
                       "timeout_seconds": 60, "idempotency_key_template": None}],
            "output_schema": None,
        },
        "parameters": {},
        "settings": {},
        "retention_days": None,
        "model": None,
        "input_schema": None,
        "permission_policy": {
            "execution_identity": "automation-default-sa",
            "allowed_tools": [],
            "allowed_registries": REGISTRIES,
            "security_mode": "normal",
            "require_approval_for": [],
            "target_scopes": {"allowed_containers": [], "allowed_repos": [], "allowed_recipients": []},
            "secrets_whitelist": [],
            "allowed_hosts": [],
            "dry_run_supported": True,
        },
        "budget": BUDGET,
        "notification_policy": NOTIFY,
        "created_by": "user",
        "source_type": "ui",
        "source_reference": None,
        "created_at": None,
        "updated_at": None,
    }


def test_modello_da_payload_stile_llm():
    auto = AutomationDefinition.model_validate({
        "name": "Briefing alle 8",
        "steps": [
            {"title": "Cerca", "tool": "brave-search", "args": {"q": "notizie"}},
            {"title": "Salva", "action": "save-report", "params": {"filename": "r.md"}, "timeout": "30",
             "input_source": "step_1"},
        ],
        "budget": {"max_tokens_per_run": 1000},
        "permission_policy": "safest",
        "schedule": None,
    })
    dump = auto.model_dump(mode="json")
    assert dump["id"] == GEN_ID
    assert dump["triggers"] == [{"id": "trg_1", "type": "cron", "cron_expression": "0 8 * * *",
                                 "timezone": "Europe/Rome", "webhook_path": None, "webhook_secret_ref": None,
                                 "webhook_token": None, "event_pattern": None, "enabled": True}]
    assert dump["workflow"] == {
        "initial_step_id": "step_1",
        "steps": [
            {"step_id": "step_1", "name": "Cerca", "type": "deterministic_action", "action_or_tool": "web_search",
             "prompt_template": None, "tools": None, "parameters": {"q": "notizie"}, "requires_approval": False,
             "condition": None, "on_failure_step_id": None, "timeout_seconds": 60, "idempotency_key_template": None},
            {"step_id": "step_2", "name": "Salva", "type": "deterministic_action", "action_or_tool": "save_artifact",
             "prompt_template": None, "tools": None,
             "parameters": {"filename": "r.md", "path": "r.md", "input_source": "step_1"},
             "requires_approval": False, "condition": None, "on_failure_step_id": None, "timeout_seconds": 30,
             "idempotency_key_template": None},
        ],
        "output_schema": None,
    }
    assert dump["budget"] == {**BUDGET, "max_tokens": 1000}
    assert sorted(dump["permission_policy"]["allowed_tools"]) == ["save_artifact", "web_search"]
    assert dump["permission_policy"]["security_mode"] == "safest"
    assert dump["permission_policy"]["allowed_registries"] == REGISTRIES


def test_modello_con_webhook():
    auto = AutomationDefinition(id="auto_hook", name="Hook", triggers=[{"type": "webhook"}],
                                workflow={"steps": [{"step_id": "a", "action": "http_get"}]})
    assert auto.model_dump(mode="json")["triggers"] == [{
        "id": "trg_1", "type": "webhook", "cron_expression": None, "timezone": "Europe/Rome",
        "webhook_path": f"/v1/automations/auto_hook/webhook/{TOKEN}", "webhook_secret_ref": None,
        "webhook_token": TOKEN, "event_pattern": None, "enabled": True,
    }]
