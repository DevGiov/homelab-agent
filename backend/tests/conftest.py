"""Conftest pytest: ambiente isolato per i test.

Imposta le env vars PRIMA dell'import di qualsiasi modulo applicativo,
così config.py legge i valori di test invece del .env reale e nessun test
scrive nei dati persistenti (es. /data nel container di produzione).

I test non marcati `live` non possono aprire connessioni di rete verso host
non locali: un servizio reale (LLM, MetaMCP, SearXNG, Letta) non mockato
fallisce subito invece di rallentare o modificare l'infrastruttura.
"""
import ipaddress
import os
import socket
import tempfile

import pytest

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


class NetworkBlockedError(ConnectionRefusedError):
    """Connessione verso un host esterno tentata da un test non `live`."""


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _is_local(address) -> bool:
    if not isinstance(address, tuple):
        return True  # socket Unix
    host = str(address[0])
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guarded_connect(self, address):
    if not _is_local(address):
        raise NetworkBlockedError(f"Rete bloccata nei test non live: connessione a {address}")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if not _is_local(address):
        raise NetworkBlockedError(f"Rete bloccata nei test non live: connessione a {address}")
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def _block_external_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        yield
        return
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    yield
