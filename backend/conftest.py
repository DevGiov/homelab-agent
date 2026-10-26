"""Conftest pytest: ambiente isolato per i test.

Imposta le env vars PRIMA dell'import di qualsiasi modulo applicativo,
così config.py legge i valori di test invece del .env reale e nessun test
scrive nei dati persistenti (es. /data nel container di produzione).
"""
import os
import sys
import tempfile

# Deve avvenire prima di ogni import di moduli backend
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="agent_test_")

os.environ["ALLOW_INSECURE"] = "1"
os.environ["API_SECRET_KEY"] = ""
os.environ["CHECKPOINT_DB_PATH"] = os.path.join(_TEST_DATA_DIR, "test_checkpoints.db")
os.environ["AUTOMATIONS_DB_PATH"] = os.path.join(_TEST_DATA_DIR, "test_automations.db")
os.environ["CALENDAR_DB_PATH"] = os.path.join(_TEST_DATA_DIR, "test_calendar.db")
os.environ["ARTIFACTS_DIR"] = os.path.join(_TEST_DATA_DIR, "artifacts")
os.environ["MEMORY_DIR"] = os.path.join(_TEST_DATA_DIR, "memory")
os.environ["ENABLE_AUTOMATION_SCHEDULER"] = "0"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
