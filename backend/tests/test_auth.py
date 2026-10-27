import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.core.config import settings

# Un endpoint per router: API principale, calendario, automazioni
PROTECTED = ["/v1/threads", "/v1/calendar/calendars", "/v1/automations"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", "chiave-di-test")
    return TestClient(api)


@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "sbagliata"}, {"X-API-Key": "chiave-di-tes"}])
def test_missing_or_wrong_key_is_rejected(client, path, headers):
    assert client.get(path, headers=headers).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_correct_key_is_accepted(client, path):
    assert client.get(path, headers={"X-API-Key": "chiave-di-test"}).status_code == 200
