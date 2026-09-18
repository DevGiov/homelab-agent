"""Test per il Subagent Coding Loop & Issue Auto-Repair (Milestone M7).

Verifica:
- Creazione e isolamento del workspace effimero
- Diagnosi con esecuzione del test runner baseline
- Ciclo iterativo a tentativi con fix e ri-test
- Calcolo della patch unified diff (.diff) e del report di riepilogo
- Gestione corretta dell'esaurimento tentativi
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from automations.loops.coding_repair import CodingRepairLoop


class TestCodingRepairLoop(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.repo_dir = os.path.join(self.tmp_dir, "mock_repo")
        os.makedirs(self.repo_dir, exist_ok=True)
        self.loop = CodingRepairLoop(workspace_base=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_already_passing_repository(self):
        """Verifica che se la baseline passa già, il loop termini immediatamente con successo."""
        math_file = os.path.join(self.repo_dir, "math_utils.py")
        with open(math_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")

        test_file = os.path.join(self.repo_dir, "test_math.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("""
import unittest
from math_utils import add

class TestMath(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

if __name__ == '__main__':
    unittest.main()
""")

        res = self.loop.run_repair_loop(
            repo_path=self.repo_dir,
            issue_description="Verifica addizione",
            test_command=[sys.executable, "test_math.py"],
            max_attempts=2,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "already_passing")
        self.assertEqual(res["attempts_used"], 0)

    def test_successful_repair_loop(self):
        """Verifica la riparazione con successo di una funzione errata al secondo tentativo."""
        calc_file = os.path.join(self.repo_dir, "calc.py")
        # Codice iniziale buggato (ritorna a - b invece di a * b)
        with open(calc_file, "w", encoding="utf-8") as f:
            f.write("def multiply(a, b):\n    return a - b\n")

        test_file = os.path.join(self.repo_dir, "test_calc.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("""
import unittest
from calc import multiply

class TestCalc(unittest.TestCase):
    def test_mult(self):
        self.assertEqual(multiply(3, 4), 12)

if __name__ == '__main__':
    unittest.main()
""")

        # Generatore simulato che al tentativo 1 sbaglia e al tentativo 2 applica la fix corretta
        def mock_fix_generator(issue, err_text, ws_path, attempt):
            if attempt == 1:
                # Fix parziale errata
                return {"calc.py": "def multiply(a, b):\n    return a + b\n"}
            # Fix corretta
            return {"calc.py": "def multiply(a, b):\n    return a * b\n"}

        res = self.loop.run_repair_loop(
            repo_path=self.repo_dir,
            issue_description="Moltiplicazione non corretta in calc.py",
            test_command=[sys.executable, "test_calc.py"],
            max_attempts=3,
            fix_generator=mock_fix_generator,
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "resolved")
        self.assertEqual(res["attempts_used"], 2)
        self.assertIn("multiply", res["patch"])
        self.assertIn("+    return a * b", res["patch"])
        self.assertIn("Summary", res["summary_md"])

    def test_exhausted_attempts(self):
        """Verifica che se tutti i tentativi falliscono, lo stato risulti 'exhausted'."""
        calc_file = os.path.join(self.repo_dir, "broken.py")
        with open(calc_file, "w", encoding="utf-8") as f:
            f.write("def value():\n    return 0\n")

        test_file = os.path.join(self.repo_dir, "test_broken.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("""
import unittest
from broken import value

class TestBroken(unittest.TestCase):
    def test_val(self):
        self.assertEqual(value(), 42)

if __name__ == '__main__':
    unittest.main()
""")

        def bad_fix_generator(issue, err_text, ws_path, attempt):
            return {"broken.py": f"def value():\n    return {attempt}\n"}

        res = self.loop.run_repair_loop(
            repo_path=self.repo_dir,
            issue_description="Risoluzione broken.py",
            test_command=[sys.executable, "test_broken.py"],
            max_attempts=2,
            fix_generator=bad_fix_generator,
        )

        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "exhausted")
        self.assertEqual(res["attempts_used"], 2)
        self.assertIsNotNone(res["last_error"])
