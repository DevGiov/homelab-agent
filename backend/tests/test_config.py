from app.core.config import Settings


def test_memory_dir_defaults_next_to_checkpoint_db(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB_PATH", "/srv/agent/checkpoints.db")
    monkeypatch.delenv("MEMORY_DIR", raising=False)
    assert Settings(_env_file=None).memory_dir == "/srv/agent/memory"


def test_explicit_memory_dir_wins(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB_PATH", "/srv/agent/checkpoints.db")
    monkeypatch.setenv("MEMORY_DIR", "/mnt/memory")
    assert Settings(_env_file=None).memory_dir == "/mnt/memory"


def test_env_vars_populate_settings(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.local, http://b.local")
    monkeypatch.setenv("SEARXNG_ENGINES", "brave")
    monkeypatch.setenv("SEARCH_PRIMARY_LANG", "it")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://a.local", "http://b.local"]
    assert s.searxng_engines == "brave"
    assert s.search_primary_lang == "it"
