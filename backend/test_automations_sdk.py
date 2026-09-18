"""Test per Custom Python SDK & Sandboxed Code Runner (Milestone M5).

Verifica:
- Validazione formale del manifest (manifest.yaml)
- Analisi statica AST contro shell injection e moduli insicuri
- Accesso controllato a variabili e secret via AutomationContext
- Esecuzione isolata con SandboxedCodeRunner e gestione timeout
- Integrazione end-to-end nello Step Runner con salvataggio artefatti
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from automations import db as auto_db
from automations.code_runner import SandboxedCodeRunner, ast_security_check, validate_manifest
from automations.models import (
    AutomationDefinition,
    ExecutionPolicy,
    RunStatus,
    StepType,
    TriggerType,
    WorkflowSpec,
    WorkflowStepDefinition,
)
from automations.runner import AutomationRunner
from sdk.context import AutomationContext
from sdk.decorators import step, workflow


class TestAutomationsSDKAndCodeRunner(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_sdk.db")
        auto_db.init_automations_db(self.db_path)
        self.runner = AutomationRunner(db_path=self.db_path)
        self.code_runner = SandboxedCodeRunner()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_manifest_validation(self):
        """Verifica la validazione formale e normalizzazione dei manifest.yaml."""
        # Manifest valido
        valid_raw = {
            "name": "backup_cleaner",
            "version": 2,
            "entrypoint": "clean.py:clean_backups",
            "permissions": {
                "allowed_tools": ["exec_host_command"],
                "secrets_whitelist": ["BACKUP_S3_KEY"],
            },
            "budget": {
                "timeout_seconds": 45,
            },
        }
        res = validate_manifest(valid_raw)
        self.assertEqual(res["name"], "backup_cleaner")
        self.assertEqual(res["version"], 2)
        self.assertEqual(res["budget"]["timeout_seconds"], 45)
        self.assertIn("BACKUP_S3_KEY", res["permissions"]["secrets_whitelist"])

        # Manifest mancante di entrypoint
        with self.assertRaises(ValueError):
            validate_manifest({"name": "incomplete_wf"})

        # Manifest mancante di name
        with self.assertRaises(ValueError):
            validate_manifest({"entrypoint": "main.py"})

    def test_ast_security_analysis(self):
        """Verifica che l'analisi statica AST intercetti chiamate e moduli malevoli."""
        # Codice pulito
        safe_code = """
import json
def run(ctx):
    val = ctx.get_input("num", 10)
    ctx.log(f"Elaborazione: {val * 2}")
    return {"result": val * 2}
"""
        violations = ast_security_check(safe_code)
        self.assertEqual(len(violations), 0)

        # Codice con import ctypes vietato
        bad_ctypes = """
import ctypes
def run(ctx):
    return ctypes.string_at(0)
"""
        violations = ast_security_check(bad_ctypes)
        self.assertTrue(any("ctypes" in v for v in violations))

        # Codice con os.system vietato
        bad_os_system = """
import os
def run(ctx):
    os.system("rm -rf /tmp/test")
"""
        violations = ast_security_check(bad_os_system)
        self.assertTrue(any("os.system" in v for v in violations))

        # Codice con subprocess(shell=True) vietato
        bad_shell = """
import subprocess
def run(ctx):
    subprocess.run("ls -la", shell=True)
"""
        violations = ast_security_check(bad_shell)
        self.assertTrue(any("shell=True" in v for v in violations))

    def test_sdk_decorators_and_context(self):
        """Verifica i decoratori @workflow, @step e la sicurezza scoped di AutomationContext."""
        @workflow(name="Test Pipeline", description="Descrizione test", timeout_seconds=120)
        class SampleWorkflow:
            @step(name="Step Uno", timeout_seconds=30)
            def first_step(self, ctx):
                return "step_1_ok"

        self.assertTrue(hasattr(SampleWorkflow, "__workflow_meta__"))
        self.assertEqual(SampleWorkflow.__workflow_meta__.name, "Test Pipeline")
        self.assertEqual(len(SampleWorkflow.__workflow_meta__.steps), 1)

        # Context: secret autorizzato vs non autorizzato
        ctx = AutomationContext(
            automation_id="auto_sec_test",
            run_id="run_123",
            step_id="step_a",
            inputs={"target": "storage1"},
            secrets={"API_KEY": "supersecret123", "PRIVATE_KEY": "forbidden456"},
            secrets_whitelist=["API_KEY"],
            artifacts_dir=os.path.join(self.tmp_dir, "artifacts"),
        )

        # Secret in whitelist: consentito
        self.assertEqual(ctx.get_secret("API_KEY"), "supersecret123")

        # Secret NON in whitelist: PermissionError categorico
        with self.assertRaises(PermissionError):
            ctx.get_secret("PRIVATE_KEY")

        # Creazione artefatto
        art = ctx.create_artifact("report.txt", "Contenuto artefatto test")
        self.assertEqual(art["name"], "report.txt")
        self.assertTrue(os.path.exists(art["storage_uri"]))
        self.assertIsNotNone(art["checksum_sha256"])

    def test_sandboxed_code_runner_execution(self):
        """Verifica l'esecuzione reale di uno script Python sandboxed tramite subprocess."""
        script_file = os.path.join(self.tmp_dir, "safe_script.py")
        with open(script_file, "w", encoding="utf-8") as f:
            f.write("""
def run(ctx):
    ctx.log("Avvio elaborazione script custom")
    item = ctx.get_input("item_name")
    sec = ctx.get_secret("ALLOWED_TOKEN")
    ctx.create_artifact("calc.json", f'{{"item": "{item}"}}', artifact_type="data", mime_type="application/json")
    return {"status": "success", "processed_item": item, "token_len": len(sec)}
""")

        context_payload = {
            "automation_id": "auto_code_test",
            "run_id": "run_sandbox_1",
            "step_id": "step_calc",
            "inputs": {"item_name": "container_404"},
            "artifacts_dir": os.path.join(self.tmp_dir, "art_sandbox"),
        }

        os.environ["ALLOWED_TOKEN"] = "token_xyz_999"
        try:
            res = self.code_runner.run_script(
                script_path=script_file,
                context_payload=context_payload,
                entrypoint_func="run",
                timeout_seconds=10,
                secrets_whitelist=["ALLOWED_TOKEN"],
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["output"]["processed_item"], "container_404")
            self.assertEqual(res["output"]["token_len"], len("token_xyz_999"))
            self.assertEqual(len(res["artifacts"]), 1)
            self.assertEqual(res["artifacts"][0]["name"], "calc.json")
        finally:
            os.environ.pop("ALLOWED_TOKEN", None)

    def test_sandboxed_code_runner_timeout_enforcement(self):
        """Verifica che uno script che va in loop infinito venga terminato rigidamente al timeout."""
        script_file = os.path.join(self.tmp_dir, "infinite_loop.py")
        with open(script_file, "w", encoding="utf-8") as f:
            f.write("""
import time
def run(ctx):
    while True:
        time.sleep(0.1)
""")

        res = self.code_runner.run_script(
            script_path=script_file,
            context_payload={"automation_id": "test_loop", "run_id": "r_loop", "step_id": "s_loop"},
            timeout_seconds=1,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "failed")
        self.assertIn("Timeout", res["error"])

    def test_end_to_end_runner_with_custom_code_step(self):
        """Verifica l'esecuzione di uno step CUSTOM_CODE all'interno di un workflow persistente."""
        script_file = os.path.join(self.tmp_dir, "e2e_code.py")
        with open(script_file, "w", encoding="utf-8") as f:
            f.write("""
def run(ctx):
    name = ctx.get_input("service_name")
    ctx.create_artifact("e2e_report.md", f"# Servizio {name}\\nTutto operativo.\\n")
    return {"healthy": True, "service": name}
""")

        auto_payload = {
            "id": "auto_custom_code_e2e",
            "name": "Custom Code E2E Workflow",
            "enabled": True,
            "triggers": [{"id": "trg_man", "type": "manual"}],
            "workflow": {
                "initial_step_id": "step_code",
                "steps": [
                    {
                        "step_id": "step_code",
                        "name": "Execute Custom Script",
                        "type": "custom_code",
                        "parameters": {
                            "script_path": script_file,
                            "entrypoint": "run",
                            "service_name": "nginx-ingress",
                        },
                        "timeout_seconds": 15,
                    }
                ],
            },
            "permission_policy": {
                "allowed_registries": ["code"],
            },
        }
        auto_db.save_definition(auto_payload, db_path=self.db_path)

        run = self.runner.start_run("auto_custom_code_e2e", trigger_type=TriggerType.MANUAL)
        self.assertEqual(run.status, RunStatus.PENDING)

        finished_run = self.runner.execute_run(run.run_id)
        self.assertEqual(finished_run.status, RunStatus.COMPLETED)
        self.assertEqual(len(finished_run.step_runs), 1)

        step_res = finished_run.step_runs[0]
        self.assertEqual(step_res.status, RunStatus.COMPLETED)
        self.assertEqual(step_res.output_payload, {"healthy": True, "service": "nginx-ingress"})

        # Verifica che l'artefatto sia stato salvato su DB
        db_artifacts = auto_db.list_artifacts(run.run_id, db_path=self.db_path)
        self.assertEqual(len(db_artifacts), 1)
        self.assertEqual(db_artifacts[0]["name"], "e2e_report.md")
