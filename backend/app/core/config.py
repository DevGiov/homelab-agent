import logging
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("config")

# Livelli che un provider cloud può ricevere da .env: `private` verso un servizio cloud si concede solo a mano
# (docs/providers/PROVIDERS_DESIGN.md, decisione 5), mai da una variabile
CLOUD_CLEARANCES = ("public", "internal")

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

    # Gli indirizzi dei servizi dipendono dall'installazione: i default qui sono neutri (localhost oppure vuoto =
    # funzione spenta) e i valori veri stanno in .env. Lo verifica tests/test_config_defaults.py
    # --- MetaMCP ---
    metamcp_url: str = Field(default="http://localhost:12008/metamcp/MetaMCP/mcp", alias="METAMCP_URL")
    metamcp_api_key: str = Field(default="", alias="METAMCP_API_KEY")

    # --- LLM ---
    # Modello delle richieste che non ne indicano uno. Vuoto = quello caricato sul server, altrimenti il primo della
    # sua lista (LLMProvider.effective_model): nessun nome nel codice, perché i modelli dipendono dall'installazione
    default_model: str = Field(default="", alias="DEFAULT_MODEL")
    llama_cpp_url: str = Field(default="http://localhost:8080/v1", alias="LLAMA_CPP_URL")
    ollama_url: str = Field(default="", alias="OLLAMA_URL")
    # Livello di sensibilità più alto che ogni provider può ricevere (public, internal, private): app.security.flows.
    # Impostazione esplicita, non dedotta dall'indirizzo. `private` vale per un server dei modelli in casa; un
    # indirizzo che porta a un servizio cloud (anche attraverso un proxy locale) va abbassato a `internal`
    llama_cpp_clearance: str = Field(default="private", alias="LLAMA_CPP_CLEARANCE")
    ollama_clearance: str = Field(default="private", alias="OLLAMA_CLEARANCE")
    # --- AWS Bedrock (provider cloud, docs/providers/PROVIDERS_DESIGN.md) ---
    # Il provider esiste solo con una chiave API oppure le credenziali AWS, la regione e almeno un modello: altrimenti
    # non c'è e nulla cambia. La chiave API ha la precedenza sulla firma SigV4 delle credenziali AWS
    bedrock_api_key: str = Field(default="", alias="BEDROCK_API_KEY", repr=False)
    aws_access_key_id: str = Field(default="", alias="AWS_ACCESS_KEY_ID", repr=False)
    aws_secret_access_key: str = Field(default="", alias="AWS_SECRET_ACCESS_KEY", repr=False)
    aws_session_token: str = Field(default="", alias="AWS_SESSION_TOKEN", repr=False)
    aws_region: str = Field(default="", alias="AWS_REGION")
    # Identificativi dei modelli offerti, separati da virgola: l'endpoint non ha un elenco (`GET /models` dà 404)
    bedrock_models: str = Field(default="", alias="BEDROCK_MODELS")
    # Livello più alto che Bedrock può ricevere: public o internal. `private` e ogni altro valore sono rifiutati
    bedrock_clearance: str = Field(default="public", alias="BEDROCK_CLEARANCE")
    # Watchdog delle risorse: dice quali modelli si possono usare. Vuoto = disattivato
    watchdog_url: str = Field(default="", alias="WATCHDOG_URL")

    # --- Canali (app.channels) ---
    # Indirizzo della Web UI per i link alle conversazioni nei canali (`<url>/c/<thread>`). È un indirizzo
    # dell'installazione: vive solo in .env. Vuoto = nessun link, i canali dicono di aprire l'app
    web_ui_url: str = Field(default="", alias="WEB_UI_URL")
    # Quanto un canale aspetta la fine del turno prima di dire che la risposta sarà nell'app (il turno continua)
    channel_reply_timeout_seconds: int = Field(default=300, alias="CHANNEL_REPLY_TIMEOUT_SECONDS")

    # --- Storage ---
    # Unica directory dei dati persistenti (database, memoria, artefatti, upload, knowledge base).
    # Default: <repo>/data, che dentro il container (backend in /app) coincide con il volume /data.
    data_dir: str = Field(default=str(BACKEND_DIR.parent / "data"), alias="DATA_DIR")
    enable_automation_scheduler: bool = Field(default=True, alias="ENABLE_AUTOMATION_SCHEDULER")
    # Osservabilità: campionamento della salute dei servizi (0 = disattivato) e conservazione delle metriche
    metrics_sample_interval_s: int = Field(default=60, alias="METRICS_SAMPLE_INTERVAL_S")
    metrics_retention_days: int = Field(default=30, alias="METRICS_RETENTION_DAYS")
    truncation_limit: int = Field(default=40000, alias="TRUNCATION_LIMIT")
    # Caratteri di ogni risultato di tool ripetuti nei passi di selezione; la sintesi finale li riceve interi
    agent_observation_limit: int = Field(default=4000, alias="AGENT_OBSERVATION_LIMIT")
    # Pensiero dei passi precedenti nell'agent loop: `auto` segue il profilo del modello (app/llm/reasoning.py), `on` e
    # `off` lo forzano (confronti nelle valutazioni)
    agent_interleaved_thinking: str = Field(default="auto", alias="AGENT_INTERLEAVED_THINKING")

    # --- Ricerca web ---
    # Vuoto = ricerca web via SearXNG disattivata
    searxng_url: str = Field(default="", alias="SEARXNG_URL")
    # Engine abilitati sull'istanza SearXNG (categoria general/web)
    searxng_engines: str = Field(default="google,bing,duckduckgo,brave,startpage", alias="SEARXNG_ENGINES")
    search_primary_lang: str = Field(default="en", alias="SEARCH_PRIMARY_LANG")
    search_fallback_lang: str = Field(default="it", alias="SEARCH_FALLBACK_LANG")

    # --- Firecracker ---
    # Vuoto = sandbox non configurata (il codice chiede l'approvazione invece di eseguire)
    firecracker_api_url: str = Field(default="", alias="FIRECRACKER_API_URL")
    firecracker_log_url: str = Field(default="", alias="FIRECRACKER_LOG_URL")
    firecracker_kernel_path: str = Field(default="/opt/firecracker/vmlinux.bin", alias="FIRECRACKER_KERNEL_PATH")
    firecracker_rootfs_path: str = Field(default="/opt/firecracker/rootfs.ext4", alias="FIRECRACKER_ROOTFS_PATH")

    @field_validator("bedrock_clearance", mode="after")
    @classmethod
    def _cloud_clearance(cls, v):
        value = str(v).strip().lower()
        if value in CLOUD_CLEARANCES:
            return value
        logger.error(f"BEDROCK_CLEARANCE={v!r} rifiutato: un provider cloud ammette solo {' o '.join(CLOUD_CLEARANCES)} "
                     f"(`private` si concede a mano, non da .env). Resta `public`.")
        return "public"

    @property
    def bedrock_model_list(self) -> List[str]:
        return [m.strip() for m in self.bedrock_models.split(",") if m.strip()]

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
        """Server MCP registrati dalla UI, impostazioni per tool, prezzi dei modelli e tetti di spesa."""
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
