"""Subagent Coding Loop per Auto-Repair di Issue e Bug (Milestone M7).

Implementa un ciclo deterministico a tentativi per la riparazione del codice:
1. Creazione di un workspace effimero isolato (copia protetta del repository)
2. Esecuzione del test runner baseline per catturare lo stacktrace di fallimento
3. Iterazione fino a N tentativi (diagnosi, applicazione patch, validazione con test)
4. Generazione automatica di patch diff (.diff) e summary report Markdown
"""

import difflib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("automations.loops.coding_repair")


class CodingRepairLoop:
    """Motore deterministico di loop di riparazione del codice in workspace effimero."""

    def __init__(self, workspace_base: Optional[str] = None):
        self.workspace_base = workspace_base

    def _setup_ephemeral_workspace(self, source_repo: str) -> str:
        """Copia i sorgenti del repository in una cartella temporanea isolata."""
        temp_dir = tempfile.mkdtemp(prefix="agy_repair_", dir=self.workspace_base)
        src_path = Path(source_repo).resolve()

        def _ignore_patterns(path, names):
            ignored = set()
            for n in names:
                if n in (".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"):
                    ignored.add(n)
            return ignored

        shutil.copytree(src_path, temp_dir, dirs_exist_ok=True, ignore=_ignore_patterns)
        return temp_dir

    def _execute_test_runner(self, workspace_path: str, test_command: Union[str, List[str]], timeout: int = 45) -> Tuple[bool, str]:
        """Esegue il comando di test all'interno del workspace effimero."""
        cmd = list(test_command) if isinstance(test_command, (list, tuple)) else test_command.split()
        if cmd and cmd[0] == "python":
            cmd[0] = sys.executable
        if cmd and "python" in os.path.basename(cmd[0]):
            if len(cmd) > 1 and cmd[1] != "-B":
                cmd.insert(1, "-B")

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = workspace_path + os.pathsep + env.get("PYTHONPATH", "")

        try:
            proc = subprocess.run(
                cmd,
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            return (proc.returncode == 0, output.strip())
        except subprocess.TimeoutExpired:
            return (False, f"Test runner superato il timeout di {timeout}s.")
        except Exception as e:
            return (False, f"Errore esecuzione test runner: {e}")

    def _compute_diff(self, original_dir: str, repaired_dir: str) -> str:
        """Calcola la patch unificata tra la directory originale e quella riparata."""
        orig_path = Path(original_dir).resolve()
        rep_path = Path(repaired_dir).resolve()
        diff_lines = []

        for r_file in rep_path.rglob("*"):
            if not r_file.is_file():
                continue
            rel = r_file.relative_to(rep_path)
            o_file = orig_path / rel

            if not o_file.exists():
                # Nuovo file creato
                r_content = r_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                diff = difflib.unified_diff([], r_content, fromfile=f"a/{rel}", tofile=f"b/{rel}")
                diff_lines.extend(diff)
            else:
                o_content = o_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                r_content = r_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                if o_content != r_content:
                    diff = difflib.unified_diff(o_content, r_content, fromfile=f"a/{rel}", tofile=f"b/{rel}")
                    diff_lines.extend(diff)

        return "".join(diff_lines)

    def run_repair_loop(
        self,
        repo_path: str,
        issue_description: str,
        test_command: Union[str, List[str]],
        max_attempts: int = 3,
        fix_generator: Optional[Callable[[str, str, str, int], Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Esegue il loop completo di riparazione del codice."""
        workspace_dir = self._setup_ephemeral_workspace(repo_path)
        logger.info(f"Avvio Coding Repair Loop per '{issue_description}' nel workspace: {workspace_dir}")

        try:
            # 1. Baseline Test Execution
            baseline_passed, baseline_output = self._execute_test_runner(workspace_dir, test_command)
            if baseline_passed:
                logger.info("I test della baseline passano già: nessuna riparazione necessaria.")
                return {
                    "success": True,
                    "status": "already_passing",
                    "attempts_used": 0,
                    "patch": "",
                    "summary_md": "# Coding Repair\n\nTutti i test passavano già con successo.",
                    "test_output": baseline_output,
                }

            logger.info(f"Baseline test fallito come previsto:\n{baseline_output[:300]}...")

            current_error = baseline_output
            patch_str = ""

            # 2. Ciclo di riparazione ad N tentativi
            for attempt in range(1, max_attempts + 1):
                logger.info(f"[Tentativo {attempt}/{max_attempts}] Diagnosi e generazione fix...")

                if fix_generator:
                    # Invocazione del generatore custom o LLM
                    files_to_modify = fix_generator(issue_description, current_error, workspace_dir, attempt)
                    if not files_to_modify or not isinstance(files_to_modify, dict):
                        logger.warning(f"Tentativo {attempt}: Il generatore non ha prodotto file da modificare.")
                        continue

                    # Applicazione delle modifiche ai file nel workspace
                    for rel_file, new_content in files_to_modify.items():
                        target_path = Path(workspace_dir) / rel_file
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        target_path.write_text(new_content, encoding="utf-8")
                else:
                    logger.warning("Nessun fix_generator configurato: impossibile applicare fix automatici.")
                    break

                # 3. Validazione con il test runner
                passed, test_out = self._execute_test_runner(workspace_dir, test_command)
                if passed:
                    logger.info(f"🎉 Riparazione riuscita con successo al tentativo {attempt}!")
                    patch_str = self._compute_diff(repo_path, workspace_dir)

                    summary_md = f"""# Coding Repair Summary

- **Issue**: {issue_description}
- **Esito**: Risolto con successo ✅
- **Tentativi impiegati**: {attempt}/{max_attempts}
- **Test Runner Output**:
```text
{test_out}
```

## Unified Diff Patch
```diff
{patch_str}
```
"""
                    return {
                        "success": True,
                        "status": "resolved",
                        "attempts_used": attempt,
                        "patch": patch_str,
                        "summary_md": summary_md,
                        "test_output": test_out,
                    }
                else:
                    logger.warning(f"Tentativo {attempt} fallito. Output del test:\n{test_out[:200]}...")
                    current_error = test_out

            # Esaurimento tentativi
            logger.error(f"Coding Repair Loop esaurito dopo {max_attempts} tentativi.")
            patch_str = self._compute_diff(repo_path, workspace_dir)
            return {
                "success": False,
                "status": "exhausted",
                "attempts_used": max_attempts,
                "last_error": current_error,
                "patch": patch_str or None,
                "summary_md": f"# Coding Repair Fallito\n\nImpossibile riparare l'issue dopo {max_attempts} tentativi.\n\nUltimo errore:\n```text\n{current_error}\n```",
            }

        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)
