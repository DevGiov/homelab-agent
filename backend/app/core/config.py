import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator
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
    llm_repeat_penalty: float = Field(default=1.10, alias="LLM_REPEAT_PENALTY")
    llm_presence_penalty: float = Field(default=0.15, alias="LLM_PRESENCE_PENALTY")
    llm_frequency_penalty: float = Field(default=0.10, alias="LLM_FREQUENCY_PENALTY")
    llm_top_p: float = Field(default=0.95, alias="LLM_TOP_P")

    # --- Letta ---
    letta_url: str = Field(default="http://192.168.1.177:8083", alias="LETTA_URL")
    letta_api_key: str = Field(default="", alias="LETTA_API_KEY")

    # --- Storage ---
    checkpoint_db_path: str = Field(default=str(BACKEND_DIR / "checkpoints.db"), alias="CHECKPOINT_DB_PATH")
    automations_db_path: str = Field(
        default=str(Path("/data/automations.db") if Path("/data").exists() and os.access("/data", os.W_OK) else BACKEND_DIR / "automations.db"),
        alias="AUTOMATIONS_DB_PATH",
    )
    calendar_db_path: str = Field(
        default=str(Path("/data/calendar.db") if Path("/data").exists() and os.access("/data", os.W_OK) else BACKEND_DIR / "calendar.db"),
        alias="CALENDAR_DB_PATH",
    )
    artifacts_dir: str = Field(
        default=str(Path("/data/artifacts") if Path("/data").exists() and os.access("/data", os.W_OK) else BACKEND_DIR / "data" / "artifacts"),
        alias="ARTIFACTS_DIR",
    )
    # Vuoto = directory "memory" accanto al DB dei checkpoint (risolta in _resolve_memory_dir)
    memory_dir: str = Field(default="", alias="MEMORY_DIR")
    enable_automation_scheduler: bool = Field(default=True, alias="ENABLE_AUTOMATION_SCHEDULER")
    truncation_limit: int = Field(default=40000, alias="TRUNCATION_LIMIT")

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

    @model_validator(mode="after")
    def _resolve_memory_dir(self):
        if not self.memory_dir:
            self.memory_dir = str(Path(self.checkpoint_db_path).parent / "memory")
        return self

    def validate_security(self) -> None:
        """Fail-fast se l'API è esposta senza chiave e senza ALLOW_INSECURE."""
        if not self.api_secret_key.strip() and not self.allow_insecure:
            raise RuntimeError(
                "API_SECRET_KEY non impostata: l'API verrebbe esposta senza autenticazione. "
                "Imposta API_SECRET_KEY in backend/.env oppure ALLOW_INSECURE=1 per ambienti di sviluppo."
            )

settings = Settings()
