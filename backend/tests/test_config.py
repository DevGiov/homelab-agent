from app.core.config import Settings


def test_every_data_path_lives_under_data_dir():
    s = Settings(_env_file=None, DATA_DIR="/srv/agent")
    assert s.checkpoint_db_path == "/srv/agent/checkpoints.db"
    assert s.automations_db_path == "/srv/agent/automations.db"
    assert s.calendar_db_path == "/srv/agent/calendar.db"
    assert (s.artifacts_dir, s.uploads_dir) == ("/srv/agent/artifacts", "/srv/agent/uploads")
    assert s.knowledge_base_dir == "/srv/agent/knowledge_base"


def test_env_vars_populate_settings(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.local, http://b.local")
    monkeypatch.setenv("SEARXNG_ENGINES", "brave")
    monkeypatch.setenv("SEARCH_PRIMARY_LANG", "it")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://a.local", "http://b.local"]
    assert s.searxng_engines == "brave"
    assert s.search_primary_lang == "it"
