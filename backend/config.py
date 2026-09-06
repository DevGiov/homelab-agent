from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(Path(__file__).parent / ".env") if (Path(__file__).parent / ".env").exists() else None, env_file_encoding="utf-8", extra="ignore")

    # --- Sicurezza (Fase 0) ---
    api_secret_key: str = Field(default="", alias="API_SECRET_KEY")
    allow_insecure: bool = Field(default=False, alias="ALLOW_INSECURE")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:4173",
        alias="CORS_ORIGINS",
    )
    rate_limit: str = Field(default="30/minute", alias="RATE_LIMIT")

    # --- MetaMCP ---
    metamcp_url: str = Field(default="http://192.168.1.175:12008/metamcp/MetaMCP/sse", alias="METAMCP_URL")
    metamcp_url_http: str = Field(default="http://192.168.1.175:12008", alias="METAMCP_URL_HTTP")
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
    checkpoint_db_path: str = Field(default=str(Path(__file__).parent / "checkpoints.db"), alias="CHECKPOINT_DB_PATH")
    truncation_limit: int = Field(default=40000, alias="TRUNCATION_LIMIT")

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

    def validate_security(self) -> None:
        """Fail-fast se l'API è esposta senza chiave e senza ALLOW_INSECURE."""
        if not self.api_secret_key.strip() and not self.allow_insecure:
            raise RuntimeError(
                "API_SECRET_KEY non impostata: l'API verrebbe esposta senza autenticazione. "
                "Imposta API_SECRET_KEY in backend/.env oppure ALLOW_INSECURE=1 per ambienti di sviluppo."
            )

_settings = Settings()

def get_settings() -> Settings:
    return _settings

# Compatibilità con il codice esistente che importa config.XXX
API_SECRET_KEY = _settings.api_secret_key
ALLOW_INSECURE = _settings.allow_insecure
CORS_ORIGINS = _settings.cors_origins
RATE_LIMIT = _settings.rate_limit
METAMCP_URL = _settings.metamcp_url
METAMCP_URL_HTTP = _settings.metamcp_url_http
METAMCP_API_KEY = _settings.metamcp_api_key
DEFAULT_MODEL = _settings.default_model
LLAMA_CPP_URL = _settings.llama_cpp_url
OLLAMA_URL = _settings.ollama_url
LETTA_URL = _settings.letta_url
LETTA_API_KEY = _settings.letta_api_key
CHECKPOINT_DB_PATH = _settings.checkpoint_db_path
TRUNCATION_LIMIT = _settings.truncation_limit
FIRECRACKER_API_URL = _settings.firecracker_api_url
FIRECRACKER_LOG_URL = _settings.firecracker_log_url
FIRECRACKER_KERNEL_PATH = _settings.firecracker_kernel_path
FIRECRACKER_ROOTFS_PATH = _settings.firecracker_rootfs_path

