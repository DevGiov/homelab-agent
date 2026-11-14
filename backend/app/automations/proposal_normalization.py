"""Passi della normalizzazione tollerante dei payload di un'automazione (scritti da un LLM o dalla UI).

`AutomationDefinition.normalize_proposal` li chiama in ordine sul dict grezzo. Lavorano su dict semplici e non
importano i modelli: i tipi validi e i default arrivano come argomenti, le istanze dei modelli arrivano già
convertite in dict.
"""
import json
import logging
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Optional

# Stesso logger dei modelli, dove il messaggio dell'inferenza è sempre stato scritto
logger = logging.getLogger("automations.models")

TEMPLATES_DIR = Path(__file__).parent / "templates"

_TOOL_ALIASES = {
    **dict.fromkeys(("http_get", "curl", "fetch_url", "web_fetch", "fetch_web"), "http_get"),
    **dict.fromkeys(("file_write", "write_file", "save_file", "save_report", "save_artifact",
                     "save_briefing_artifact"), "save_artifact"),
    **dict.fromkeys(("web_search", "search", "google", "brave_search"), "web_search"),
}

# Frasi che fissano l'orario, nell'ordine in cui vengono cercate; la prima trovata vince
_CRON_PHRASES = (
    (("mezzogiorno", "alle 12", "ore 12"), "0 12 * * *"),
    (("alle 10", "ore 10"), "0 10 * * *"),
    (("alle 9", "ore 9", "alle 09"), "0 9 * * *"),
    (("alle 8", "ore 8", "alle 08"), "0 8 * * *"),
    (("ogni ora", "hourly"), "0 * * * *"),
)
_CLOCK_TIME = re.compile(r'(?:alle|ore|at)\s+([0-2]?\d)[:.]([0-5]\d)')


# --- Identità, parametri e forma del workflow ---

def normalize_identity(d: dict) -> None:
    """Normalizza id (generato se manca) e name (l'id se manca)."""
    if not d.get("id"):
        d["id"] = f"auto_{uuid.uuid4().hex[:8]}"
    if not d.get("name"):
        d["name"] = d.get("id", "Nuova Automazione")


def normalize_parameters_and_settings(d: dict) -> None:
    """Normalizza parameters e settings dai loro alias; un valore che non è un dict diventa {}."""
    raw_params = d.get("parameters") or d.get("params") or d.get("inputs") or d.get("config") or {}
    d["parameters"] = dict(raw_params) if isinstance(raw_params, dict) else {}
    raw_settings = d.get("settings") or d.get("custom_settings") or {}
    d["settings"] = dict(raw_settings) if isinstance(raw_settings, dict) else {}


def _first_step_id(steps: list) -> str:
    """Id iniziale di una lista di step grezzi: step_id o id del primo step, altrimenti "step_1"."""
    first_step = steps[0] if (steps and isinstance(steps[0], dict)) else {}
    return first_step.get("step_id") or first_step.get("id") or "step_1"


def normalize_workflow_shape(d: dict) -> None:
    """Normalizza il workflow in un dict con initial_step_id e steps, da una lista o dagli steps di primo livello."""
    wf = d.get("workflow")
    if isinstance(wf, list):
        steps = list(wf)
        d["workflow"] = {"initial_step_id": _first_step_id(steps), "steps": steps}
    elif isinstance(wf, dict):
        wf = dict(wf)
        if not wf.get("initial_step_id") and wf.get("steps") and isinstance(wf["steps"][0], dict):
            wf["initial_step_id"] = _first_step_id(wf["steps"])
        d["workflow"] = wf
    elif not wf and "steps" in d:
        steps = list(d.pop("steps"))
        d["workflow"] = {"initial_step_id": _first_step_id(steps), "steps": steps}


# --- Espansione da template ---

def _single_step_action(d: dict) -> Optional[str]:
    """Azione dell'unico step del workflow (minuscola, '-' come '_'), o None se il workflow non ha un solo step."""
    workflow = d.get("workflow")
    if not (isinstance(workflow, dict) and "steps" in workflow):
        return None
    steps = workflow["steps"]
    if len(steps) != 1 or not isinstance(steps[0], dict):
        return None
    return str(steps[0].get("action_or_tool") or steps[0].get("action") or "").lower().replace("-", "_")


def _template_matches(stem: str, action: str) -> bool:
    """Vero se il nome del template e l'azione (almeno 5 caratteri) sono uno contenuto nell'altro."""
    stem_clean = stem.lower().replace("-", "_")
    return (stem_clean in action or action in stem_clean) and len(action) >= 5


def _apply_template(d: dict, template: dict) -> None:
    """Copia nel payload gli step, lo step iniziale e la permission policy del template."""
    d["workflow"]["steps"] = template["workflow"]["steps"]
    d["workflow"]["initial_step_id"] = template["workflow"].get("initial_step_id", "step_1")
    if "permission_policy" in template:
        d["permission_policy"] = template["permission_policy"]


def expand_single_step_template(d: dict) -> None:
    """Sostituisce un workflow di un solo step con il primo template il cui nome corrisponde all'azione dello step."""
    action = _single_step_action(d)
    if action is None or not TEMPLATES_DIR.exists():
        return
    for tpl_file in TEMPLATES_DIR.glob("*.json"):
        if not _template_matches(tpl_file.stem, action):
            continue
        try:
            with open(tpl_file, "r", encoding="utf-8") as tf:
                template = json.load(tf)
            if "workflow" in template and "steps" in template["workflow"]:
                _apply_template(d, template)
                break
        except Exception:
            pass


# --- Step ---

def _canonical_tool(tool: Any) -> Optional[str]:
    """Nome canonico di un tool noto scritto con un alias (maiuscole e '-' ammessi), o None."""
    return _TOOL_ALIASES.get(str(tool).lower().replace("-", "_"))


def _step_parameters(s: dict) -> dict:
    """Normalizza i parametri dello step dai loro alias, con input_source e content_source e filename come path."""
    raw = s.get("parameters") or s.get("arguments") or s.get("args") or s.get("params") or {}
    params = dict(raw) if isinstance(raw, dict) else {}
    for key in ("input_source", "content_source"):
        if key in s and key not in params:
            params[key] = s[key]
    if "filename" in params and "path" not in params:
        params["path"] = params["filename"]
    return params


def _step_type(s: dict, step_types: set[str]) -> str:
    """Normalizza il tipo dello step: un valore valido resta, alias e prompt lo scelgono, altrimenti deterministico."""
    raw_type = str(s.get("type", "")).lower()
    if raw_type in step_types:
        return raw_type
    if (
        raw_type in ("llm_call", "agent", "llm", "agent_task", "agentic_task", "ai_task", "ai")
        or bool(s.get("prompt_template"))
    ):
        return "agentic_task"
    if raw_type in ("code", "python", "script"):
        return "custom_code"
    if raw_type in ("approval", "gate", "approval_gate"):
        return "approval_gate"
    return "deterministic_action"


def _normalize_step(s: dict, idx: int, step_types: set[str]) -> dict:
    """Normalizza uno step: id, nome, azione, parametri, prompt, tipo e timeout."""
    if not s.get("step_id"):
        s["step_id"] = s.get("id") or f"step_{idx+1}"
    if not s.get("name"):
        s["name"] = s.get("title") or s.get("step_id") or f"Step {idx+1}"
    if not s.get("action_or_tool"):
        s["action_or_tool"] = s.get("action") or s.get("tool")
    s["parameters"] = _step_parameters(s)
    if not s.get("prompt_template"):
        s["prompt_template"] = (
            s.get("prompt") or s.get("instruction") or s.get("task") or s["parameters"].get("prompt")
        )
    tool = s.get("action_or_tool")
    if tool:
        s["action_or_tool"] = _canonical_tool(tool) or tool
    s["type"] = _step_type(s, step_types)
    if "timeout" in s and "timeout_seconds" not in s:
        s["timeout_seconds"] = int(s["timeout"])
    return s


def normalize_steps(d: dict, step_types: set[str]) -> None:
    """Normalizza gli step del workflow (valori di StepType in step_types), scartando quelli che non sono dict."""
    workflow = d.get("workflow")
    if not (isinstance(workflow, dict) and "steps" in workflow):
        return
    workflow["steps"] = [
        _normalize_step(dict(s), idx, step_types)
        for idx, s in enumerate(workflow["steps"])
        if isinstance(s, dict)
    ]


# --- Trigger ---

def _manual_trigger() -> dict:
    """Trigger manuale di ripiego, quando il payload non ne ha di validi."""
    return {"id": "trg_manual", "type": "manual", "enabled": True}


def _coerce_triggers(d: dict) -> Any:
    """Normalizza la forma di triggers: un dict, una stringa (cron se ha cifre o '*') o il cron di primo livello."""
    trgs = d.get("triggers")
    if isinstance(trgs, dict):
        return [trgs]
    if isinstance(trgs, str):
        clean_str = trgs.strip()
        if any(c in clean_str for c in "*0123456789"):
            return [{"type": "cron", "cron_expression": clean_str}]
        return [{"type": "manual"}]
    if not trgs and (d.get("cron") or d.get("schedule") or d.get("cron_expression")):
        expr = d.get("cron_expression") or d.get("schedule") or d.get("cron")
        return [{"type": "cron", "cron_expression": str(expr)}]
    return trgs


def _has_explicit_cron(trgs: Any) -> bool:
    """Vero se un trigger dict dichiara un cron: type "cron", cron_expression, schedule o cron."""
    if not isinstance(trgs, list):
        return False
    return any(
        isinstance(t, dict)
        and (t.get("type") == "cron" or t.get("cron_expression") or t.get("schedule") or t.get("cron"))
        for t in trgs
    )


def _infer_cron(text: str) -> Optional[str]:
    """Espressione cron dedotta da un testo minuscolo ("mezzogiorno", "alle 10", "ogni ora", "alle 18:30"), o None."""
    for phrases, expression in _CRON_PHRASES:
        if any(phrase in text for phrase in phrases):
            return expression
    m = _CLOCK_TIME.search(text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return f"{mn} {h} * * *"
    return None


def _add_inferred_cron(d: dict, trgs: Any) -> Any:
    """Aggiunge ai trigger il cron dedotto da name e description, se nessuno dichiara già un cron."""
    if _has_explicit_cron(trgs):
        return trgs
    inferred_cron = _infer_cron(f"{d.get('name', '')} {d.get('description', '')}".lower())
    if not inferred_cron:
        return trgs
    logger.info(f"Inferito trigger cron '{inferred_cron}' per automazione '{d.get('id')}' da testo descrittivo.")
    trigger = {"type": "cron", "cron_expression": inferred_cron, "timezone": "Europe/Rome"}
    if not trgs or not isinstance(trgs, list):
        return [trigger]
    trgs.append(trigger)  # la lista è quella del payload ricevuto: viene modificata anche lì
    return trgs


def _trigger_type(t: dict, trigger_types: set[str]) -> str:
    """Normalizza il tipo del trigger: mancante, non valido o manual con un'espressione diventa cron o manual."""
    raw_t_type = str(t.get("type", "")).lower()
    if not raw_t_type or raw_t_type not in trigger_types:
        raw_t_type = "cron" if t.get("cron_expression") else "manual"
    if t.get("cron_expression") and raw_t_type == "manual":
        raw_t_type = "cron"
    return raw_t_type


def _normalize_trigger(t: dict, idx: int, automation_id: Any, trigger_types: set[str]) -> dict:
    """Normalizza un trigger: id, espressione cron dai sinonimi, tipo, token e path del webhook, timezone, enabled."""
    if not t.get("id"):
        t["id"] = f"trg_{idx+1}"
    cron_expr = (
        t.get("cron_expression") or t.get("schedule") or t.get("cron") or t.get("cron_expr") or t.get("expression")
    )
    if cron_expr:
        t["cron_expression"] = str(cron_expr).strip()
    t["type"] = _trigger_type(t, trigger_types)
    if t["type"] == "cron" and not t.get("cron_expression"):
        t["cron_expression"] = "0 9 * * *"
    elif t["type"] == "webhook":
        if not t.get("webhook_token"):
            t["webhook_token"] = secrets.token_urlsafe(24)
        if not t.get("webhook_path") and automation_id:
            t["webhook_path"] = f"/v1/automations/{automation_id}/webhook/{t['webhook_token']}"
    if not t.get("timezone"):
        t["timezone"] = "Europe/Rome"
    if "enabled" not in t:
        t["enabled"] = True
    return t


def normalize_triggers(d: dict, trigger_types: set[str]) -> None:
    """Normalizza i trigger (valori di TriggerType in trigger_types); senza trigger validi resta uno manuale."""
    trgs = _add_inferred_cron(d, _coerce_triggers(d))
    if not trgs or not isinstance(trgs, list):
        d["triggers"] = [_manual_trigger()]
        return
    norm_trgs = [
        _normalize_trigger(dict(t), idx, d.get("id"), trigger_types)
        for idx, t in enumerate(trgs)
        if isinstance(t, dict)
    ]
    d["triggers"] = norm_trgs or [_manual_trigger()]


# --- Budget, permission policy e notifiche ---

def _merge_defaults(values: dict, defaults: dict) -> dict:
    """I default aggiornati con i valori che non sono None."""
    return {**defaults, **{k: v for k, v in values.items() if v is not None}}


def normalize_budget(budget: Any, defaults: dict) -> dict:
    """Normalizza il budget: alias di max_tokens e max_duration_seconds, sopra i default; un non dict dà i default."""
    if not isinstance(budget, dict):
        return defaults
    b_dict = dict(budget)
    if "max_tokens_per_run" in b_dict and "max_tokens" not in b_dict:
        b_dict["max_tokens"] = b_dict["max_tokens_per_run"]
    if "timeout_seconds" in b_dict and "max_duration_seconds" not in b_dict:
        b_dict["max_duration_seconds"] = b_dict["timeout_seconds"]
    if "duration_seconds" in b_dict and "max_duration_seconds" not in b_dict:
        b_dict["max_duration_seconds"] = b_dict["duration_seconds"]
    return _merge_defaults(b_dict, defaults)


def _policy_dict(policy: Any) -> dict:
    """Permission policy come dict: una stringa dà solo la security_mode ("normal" se non è una modalità nota)."""
    if isinstance(policy, dict):
        return dict(policy)
    if isinstance(policy, str):
        p_lower = policy.lower()
        return {"security_mode": p_lower if p_lower in ("safest", "normal", "dangerous") else "normal"}
    return {}


def _workflow_tools(workflow: Any) -> set:
    """Azioni degli step del workflow normalizzato."""
    tools = set()
    if isinstance(workflow, dict):
        for st in workflow.get("steps", []):
            if isinstance(st, dict) and st.get("action_or_tool"):
                tools.add(st["action_or_tool"])
    return tools


def _with_canonical_aliases(allowed_tools: Any) -> set:
    """Tool ammessi con, per ogni alias noto, anche il suo nome canonico."""
    norm_tools = set()
    for t in allowed_tools:
        norm_tools.add(t)
        canonical = _canonical_tool(t)
        if canonical:
            norm_tools.add(canonical)
    return norm_tools


def normalize_permission_policy(policy: Any, workflow: Any) -> dict:
    """Normalizza la permission policy: allowed_tools dagli step o con i nomi canonici, registries di default."""
    p_copy = _policy_dict(policy)
    if not p_copy.get("allowed_tools"):
        p_copy["allowed_tools"] = list(_workflow_tools(workflow))
    else:
        p_copy["allowed_tools"] = list(_with_canonical_aliases(p_copy["allowed_tools"]))
    if "allowed_registries" not in p_copy or not p_copy["allowed_registries"]:
        p_copy["allowed_registries"] = ["mcp", "web", "code", "memory", "vision", "email", "automations"]
    return p_copy


def normalize_notification_policy(policy: Any, defaults: dict) -> dict:
    """Normalizza la notification policy: i valori non None del dict sopra i default; un non dict dà i default."""
    if not isinstance(policy, dict):
        return defaults
    return _merge_defaults(policy, defaults)
