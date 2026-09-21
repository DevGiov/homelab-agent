"""Motore di introspezione ed estrazione parametri per le Automazioni.

Analizza staticamente le definizioni di automazione:
- Template dei prompt per {{inputs.XYZ}}, {{config.XYZ}}, {{secrets.XYZ}}
- Argomenti e parametri di workflow step
- Codice Python custom per os.environ, params, inputs
Restituisce un catalogo di variabili attese con tipo inferito e metadati.
"""

import ast
import re
from typing import Any, Dict, List, Optional


def introspect_automation_parameters(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Estrae l'elenco delle variabili e dei parametri utilizzati dall'automazione."""
    detected: Dict[str, Dict[str, Any]] = {}

    def _register(key: str, inferred_type: str, source: str, default: Any = None,
                  required: bool = False, description: str = ""):
        clean_key = key.strip()
        if not clean_key or clean_key in ("date", "datetime", "run_id", "automation_id"):
            return
        if clean_key not in detected:
            detected[clean_key] = {
                "key": clean_key,
                "type": inferred_type,
                "source": source,
                "default": default,
                "required": required,
                "description": description or f"Variabile '{clean_key}' rilevata in {source}",
            }
        else:
            # Aggiorna se la nuova rilevazione ha una descrizione o default più informativo
            if description and not detected[clean_key].get("description"):
                detected[clean_key]["description"] = description
            if default is not None and detected[clean_key].get("default") is None:
                detected[clean_key]["default"] = default
            if required:
                detected[clean_key]["required"] = True

    # 1. Scansione parametri già configurati a livello root
    root_params = definition.get("parameters") or {}
    if isinstance(root_params, dict):
        for k, v in root_params.items():
            inferred = "string"
            if isinstance(v, bool):
                inferred = "boolean"
            elif isinstance(v, (int, float)):
                inferred = "number"
            elif any(s in k.lower() for s in ("token", "key", "secret", "password")):
                inferred = "secret"
            _register(k, inferred, "configured_parameters", default=v, description=f"Parametro configurato ({k})")

    # 2. Scansione degli Step del Workflow
    wf = definition.get("workflow") or {}
    steps = wf.get("steps") if isinstance(wf, dict) else (wf if isinstance(wf, list) else [])

    for s in steps:
        if not isinstance(s, dict):
            continue

        step_id = s.get("step_id") or s.get("id", "step")

        # 2.1 Prompt Template
        prompt = s.get("prompt_template") or s.get("prompt") or s.get("instruction") or ""
        if isinstance(prompt, str) and prompt:
            matches = re.findall(r"\{\{([a-zA-Z0-9_\.]+)\}\}", prompt)
            for m in matches:
                parts = m.split(".")
                prefix = parts[0]
                var_name = parts[1] if len(parts) > 1 else m

                if prefix in ("inputs", "config", "params"):
                    inferred = "secret" if any(sec in var_name.lower() for sec in ("token", "key", "secret", "password")) else "string"
                    _register(var_name, inferred, f"prompt:{step_id}", required=True)
                elif prefix == "secrets":
                    _register(var_name, "secret", f"secrets:{step_id}", required=True, description=f"Chiave/Secret sicuro '{var_name}'")

        # 2.2 Parameters dello step
        params = s.get("parameters") or s.get("arguments") or s.get("args") or {}
        if isinstance(params, dict):
            for pk, pv in params.items():
                if isinstance(pv, str):
                    matches = re.findall(r"\{\{([a-zA-Z0-9_\.]+)\}\}", pv)
                    for m in matches:
                        parts = m.split(".")
                        prefix = parts[0]
                        var_name = parts[1] if len(parts) > 1 else m
                        if prefix in ("inputs", "config", "params"):
                            _register(var_name, "string", f"param:{step_id}:{pk}")
                        elif prefix == "secrets":
                            _register(var_name, "secret", f"secrets:{step_id}:{pk}", required=True)

        # 2.3 Custom Python Code
        code = s.get("custom_code") or s.get("code") or (params.get("code") if isinstance(params, dict) else None)
        if isinstance(code, str) and code.strip():
            # Analisi AST
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    # os.environ.get("VAR") o os.environ["VAR"]
                    if isinstance(node, ast.Subscript):
                        if (
                            isinstance(node.value, ast.Attribute)
                            and node.value.attr == "environ"
                            and isinstance(node.slice, ast.Constant)
                            and isinstance(node.slice.value, str)
                        ):
                            k = node.slice.value
                            inferred = "secret" if any(sec in k.lower() for sec in ("token", "key", "secret", "password")) else "string"
                            _register(k, inferred, f"python_code:{step_id}", required=True)
                    elif isinstance(node, ast.Call):
                        # os.getenv("VAR", default) o os.environ.get("VAR", default)
                        is_getenv = isinstance(node.func, ast.Attribute) and node.func.attr in ("getenv", "get")
                        if is_getenv and node.args:
                            first_arg = node.args[0]
                            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                                k = first_arg.value
                                def_val = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
                                inferred = "secret" if any(sec in k.lower() for sec in ("token", "key", "secret", "password")) else "string"
                                _register(k, inferred, f"python_code:{step_id}", default=def_val)
            except Exception:
                # Fallback con espressioni regolari se il parsing AST fallisce
                env_matches = re.findall(r"""(?:os\.environ(?:\[|\.get\()|os\.getenv\()[\"']([A-Za-z0-9_]+)[\"']""", code)
                for em in env_matches:
                    inferred = "secret" if any(sec in em.lower() for sec in ("token", "key", "secret", "password")) else "string"
                    _register(em, inferred, f"python_code:{step_id}")

    results = sorted(list(detected.values()), key=lambda x: (not x.get("required"), x["key"]))
    for r in results:
        r["name"] = r["key"]
        r["inferred_type"] = r["type"]

    return {
        "variables": results,
        "parameters": [r for r in results if r.get("type") != "secret"],
        "secrets": [r for r in results if r.get("type") == "secret"],
    }
