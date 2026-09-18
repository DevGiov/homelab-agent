"""Sandboxed Code Runner per Automations & Loops (Milestone M5).

Gestisce l'esecuzione sicura di script e workflow Python custom:
- Validazione formale del manifest (manifest.yaml)
- Analisi statica AST di sicurezza per prevenire shell injection e monkey-patching
- Esecuzione isolata in subprocess protetto con variabili d'ambiente controllate
- Enforcing di timeout rigidi ed estrazione di log e artefatti
"""

import ast
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger("automations.code_runner")

# Moduli e chiamate vietate categoricamente dall'analisi statica AST
DISALLOWED_MODULES = {
    "ctypes",
    "pty",
    "posix",
    "_posixsubprocess",
}

DISALLOWED_ATTR_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("os", "kill"),
    ("os", "killpg"),
}


def validate_manifest(manifest_data: Union[str, Path, Dict[str, Any]]) -> Dict[str, Any]:
    """Valida il manifest.yaml di un'automazione basata su codice Python."""
    if isinstance(manifest_data, (str, Path)):
        manifest_path = Path(manifest_data)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest file non trovato: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    elif isinstance(manifest_data, dict):
        data = manifest_data
    else:
        raise ValueError("manifest_data deve essere un path a file o un dizionario.")

    if not isinstance(data, dict):
        raise ValueError("Il manifest deve essere un dizionario valido.")

    # Campi obbligatori
    if not data.get("name"):
        raise ValueError("Il manifest richiede il campo 'name'.")
    if not data.get("entrypoint"):
        raise ValueError("Il manifest richiede il campo 'entrypoint' (es. 'main.py:run' o 'main.py').")

    # Normalizzazione permessi e whitelist
    perms = data.get("permissions", {})
    clean_manifest = {
        "name": str(data["name"]),
        "version": int(data.get("version", 1)),
        "description": str(data.get("description", "")),
        "entrypoint": str(data["entrypoint"]),
        "permissions": {
            "allowed_tools": list(perms.get("allowed_tools", [])),
            "allowed_registries": list(perms.get("allowed_registries", ["code"])),
            "secrets_whitelist": list(perms.get("secrets_whitelist", [])),
        },
        "budget": {
            "timeout_seconds": max(1, int(data.get("budget", {}).get("timeout_seconds", 60))),
            "max_memory_mb": int(data.get("budget", {}).get("max_memory_mb", 256)),
        },
    }
    return clean_manifest


def ast_security_check(code_str: str) -> List[str]:
    """Esegue un'analisi statica AST sul codice Python alla ricerca di costrutti insicuri."""
    violations: List[str] = []
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return [f"Errore di sintassi Python: {e}"]

    for node in ast.walk(tree):
        # 1. Controllo import vietati
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg in DISALLOWED_MODULES:
                    violations.append(f"Import vietato del modulo '{root_pkg}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in DISALLOWED_MODULES:
                    violations.append(f"Import vietato dal modulo '{root_pkg}'")

        # 2. Controllo chiamate di sistema pericolose (os.system, os.popen)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    call_tuple = (node.func.value.id, node.func.attr)
                    if call_tuple in DISALLOWED_ATTR_CALLS:
                        violations.append(f"Chiamata vietata a '{call_tuple[0]}.{call_tuple[1]}'")

            # Controllo subprocess(..., shell=True)
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    violations.append("Uso di shell=True in chiamate subprocess è vietato dalla policy")

    return violations


class SandboxedCodeRunner:
    """Esegue codice Python in un processo separato a basso privilegio con timeout e controlli."""

    def __init__(self, backend_dir: Optional[str] = None):
        self.backend_dir = backend_dir or str(Path(__file__).resolve().parent.parent)

    def run_script(
        self,
        script_path: Union[str, Path],
        context_payload: Dict[str, Any],
        entrypoint_func: Optional[str] = None,
        timeout_seconds: int = 60,
        secrets_whitelist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Esegue uno script Python dopo verifica AST e ne raccoglie l'output strutturato."""
        script_path = Path(script_path).resolve()
        if not script_path.exists():
            return {
                "success": False,
                "status": "failed",
                "error": f"Script non trovato: {script_path}",
                "output": None,
            }

        code_text = script_path.read_text(encoding="utf-8")
        violations = ast_security_check(code_text)
        if violations:
            logger.warning(f"Violazioni di sicurezza rilevate in '{script_path}': {violations}")
            return {
                "success": False,
                "status": "failed",
                "error": f"Analisi di sicurezza fallita: {'; '.join(violations)}",
                "output": None,
            }

        # Preparazione ambiente isolato
        clean_env = {
            "PYTHONPATH": self.backend_dir,
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
        }

        # Passaggio delle sole variabili d'ambiente autorizzate in secrets_whitelist
        allowed_secrets = set(secrets_whitelist or [])
        for s in allowed_secrets:
            if s in os.environ:
                clean_env[s] = os.environ[s]

        # Script runner in-line che esegue il file e gestisce AutomationContext
        worker_code = f"""
import sys, json, os
from pathlib import Path
import importlib.util

from sdk.context import AutomationContext

payload = json.loads(sys.stdin.read())
ctx_data = payload.get("context", {{}})
secrets = payload.get("secrets", {{}})
secrets_whitelist = payload.get("secrets_whitelist", [])

ctx = AutomationContext(
    automation_id=ctx_data.get("automation_id", "custom_code"),
    run_id=ctx_data.get("run_id", "run_custom"),
    step_id=ctx_data.get("step_id", "step_custom"),
    inputs=ctx_data.get("inputs", {{}}),
    step_outputs=ctx_data.get("step_outputs", {{}}),
    secrets=secrets,
    secrets_whitelist=secrets_whitelist,
    artifacts_dir=ctx_data.get("artifacts_dir")
)

script_file = Path(r"{script_path}")
spec = importlib.util.spec_from_file_location("custom_user_module", script_file)
mod = importlib.util.module_from_spec(spec)
sys.modules["custom_user_module"] = mod

try:
    spec.loader.exec_module(mod)
    entry_name = "{entrypoint_func or ''}"
    if entry_name and hasattr(mod, entry_name):
        target = getattr(mod, entry_name)
    elif hasattr(mod, "main"):
        target = getattr(mod, "main")
    elif hasattr(mod, "run"):
        target = getattr(mod, "run")
    else:
        # Se non c'è funzione specifica, l'esecuzione del modulo stesso è considerata il run
        target = None

    if target:
        import inspect
        sig = inspect.signature(target)
        if len(sig.parameters) == 1:
            res = target(ctx)
        else:
            res = target()
    else:
        res = getattr(mod, "result", None)

    # Serializzazione output
    out = {{
        "success": True,
        "output": res,
        "logs": ctx.logs,
        "artifacts": ctx.created_artifacts
    }}
    print("===RESULT_START===")
    print(json.dumps(out, ensure_ascii=False, default=str))
    print("===RESULT_END===")
except Exception as e:
    import traceback
    err_out = {{
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
        "logs": ctx.logs,
        "artifacts": ctx.created_artifacts
    }}
    print("===RESULT_START===")
    print(json.dumps(err_out, ensure_ascii=False, default=str))
    print("===RESULT_END===")
    sys.exit(1)
"""

        input_data = {
            "context": context_payload,
            "secrets": {k: os.environ.get(k, "") for k in allowed_secrets if k in os.environ},
            "secrets_whitelist": list(allowed_secrets),
        }

        try:
            proc = subprocess.run(
                [sys.executable, "-u", "-c", worker_code],
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                env=clean_env,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "status": "failed",
                "error": f"Timeout di esecuzione superato ({timeout_seconds}s).",
                "output": None,
            }

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # Estrazione del JSON tra i marcatori
        if "===RESULT_START===" in stdout and "===RESULT_END===" in stdout:
            part = stdout.split("===RESULT_START===")[1].split("===RESULT_END===")[0].strip()
            try:
                res_obj = json.loads(part)
                if res_obj.get("success"):
                    return {
                        "success": True,
                        "status": "completed",
                        "output": res_obj.get("output"),
                        "logs": res_obj.get("logs", []),
                        "artifacts": res_obj.get("artifacts", []),
                    }
                else:
                    return {
                        "success": False,
                        "status": "failed",
                        "error": res_obj.get("error"),
                        "traceback": res_obj.get("traceback"),
                        "logs": res_obj.get("logs", []),
                        "artifacts": res_obj.get("artifacts", []),
                    }
            except Exception as e:
                return {
                    "success": False,
                    "status": "failed",
                    "error": f"Errore parsing output runner: {e}",
                    "raw_stdout": stdout,
                }

        # Se il processo è uscito con errore senza marcatori validi
        return {
            "success": False,
            "status": "failed",
            "error": stderr.strip() or f"Processo terminato con codice {proc.returncode}",
            "raw_stdout": stdout,
        }
