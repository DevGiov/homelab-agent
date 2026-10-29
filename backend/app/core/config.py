from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Radice del backend (contiene app/, sdk/ e .env)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env") if (BACKEND_DIR / ".env").exists() else None, env_file_encoding="utf-8", extra="ignore")

    # --- Sicurezza (Fase 0) ---
    api_secret_key: str = Field(default="", alias="API_SECRET_KEY")
    allow_insecure: bool = Field(default=False, alias="ALLOW_INSECURE")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:4173",
        alias="CORS_ORIGINS",
    )
    rate_limit: str = Field(default="30/minute", alias="RATE_LIMIT")

    # --- MetaMCP ---
    metamcp_url: str = Field(default="http://192.168.1.175:12008/metamcp/MetaMCP/mcp", alias="METAMCP_URL")
    metamcp_api_key: str = Field(default="", alias="METAMCP_API_KEY")

    # --- LLM ---
    default_model: str = Field(default="Qwen3.6-35B-HugeCtx", alias="DEFAULT_MODEL")
    llama_cpp_url: str = Field(default="http://192.168.1.159:8080/v1", alias="LLAMA_CPP_URL")
    ollama_url: str = Field(default="", alias="OLLAMA_URL")

    # --- Storage ---
    # Unica directory dei dati persistenti (database, memoria, artefatti, upload, knowledge base).
    # Default: <repo>/data, che dentro il container (backend in /app) coincide con il volume /data.
    data_dir: str = Field(default=str(BACKEND_DIR.parent / "data"), alias="DATA_DIR")
    enable_automation_scheduler: bool = Field(default=True, alias="ENABLE_AUTOMATION_SCHEDULER")
    # Osservabilità: campionamento della salute dei servizi (0 = disattivato) e conservazione delle metriche
    metrics_sample_interval_s: int = Field(default=60, alias="METRICS_SAMPLE_INTERVAL_S")
    metrics_retention_days: int = Field(default=30, alias="METRICS_RETENTION_DAYS")
    # Ora (0-23, fuso del container: UTC salvo TZ) del consolidamento giornaliero della memoria; -1 = solo su richiesta
    memory_consolidation_hour: int = Field(default=3, alias="MEMORY_CONSOLIDATION_HOUR")
    truncation_limit: int = Field(default=40000, alias="TRUNCATION_LIMIT")
    # Caratteri di ogni risultato di tool ripetuti nei passi di selezione; la sintesi finale li riceve interi
    agent_observation_limit: int = Field(default=4000, alias="AGENT_OBSERVATION_LIMIT")

    # --- Ricerca web ---
    searxng_url: str = Field(default="http://192.168.1.161:8080", alias="SEARXNG_URL")
    # Engine abilitati sull'istanza SearXNG (categoria general/web)
    searxng_engines: str = Field(default="google,bing,duckduckgo,brave,startpage", alias="SEARXNG_ENGINES")
    search_primary_lang: str = Field(default="en", alias="SEARCH_PRIMARY_LANG")
    search_fallback_lang: str = Field(default="it", alias="SEARCH_FALLBACK_LANG")

    # --- Firecracker ---
    firecracker_api_url: str = Field(default="http://192.168.1.69:8080", alias="FIRECRACKER_API_URL")
    firecracker_log_url: str = Field(default="http://192.168.1.69:8081/console.log", alias="FIRECRACKER_LOG_URL")
    firecracker_kernel_path: str = Field(default="/opt/firecracker/vmlinux.bin", alias="FIRECRACKER_KERNEL_PATH")
    firecracker_rootfs_path: str = Field(default="/opt/firecracker/rootfs.ext4", alias="FIRECRACKER_ROOTFS_PATH")

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # --- Percorsi derivati da data_dir: non configurabili singolarmente ---
    @property
    def checkpoint_db_path(self) -> str:
        """Checkpoint LangGraph, thread, audit, permessi e memoria vettoriale."""
        return str(Path(self.data_dir) / "checkpoints.db")

    @property
    def automations_db_path(self) -> str:
        return str(Path(self.data_dir) / "automations.db")

    @property
    def calendar_db_path(self) -> str:
        return str(Path(self.data_dir) / "calendar.db")

    @property
    def metrics_db_path(self) -> str:
        """Chiamate LLM, turni e campioni di salute dei servizi."""
        return str(Path(self.data_dir) / "metrics.db")

    @property
    def mcp_db_path(self) -> str:
        """Server MCP registrati dalla UI e impostazioni per tool."""
        return str(Path(self.data_dir) / "mcp.db")

    @property
    def artifacts_dir(self) -> str:
        return str(Path(self.data_dir) / "artifacts")

    @property
    def uploads_dir(self) -> str:
        return str(Path(self.data_dir) / "uploads")

    @property
    def knowledge_base_dir(self) -> str:
        return str(Path(self.data_dir) / "knowledge_base")

    def validate_security(self) -> None:
        """Fail-fast se l'API è esposta senza chiave e senza ALLOW_INSECURE."""
        if not self.api_secret_key.strip() and not self.allow_insecure:
            raise RuntimeError(
                "API_SECRET_KEY non impostata: l'API verrebbe esposta senza autenticazione. "
                "Imposta API_SECRET_KEY in backend/.env oppure ALLOW_INSECURE=1 per ambienti di sviluppo."
            )

settings = Settings()
