import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.deps import limiter
from app.api.routes import approvals, chat, kb, memory, providers, system, threads, uploads
from app.automations.db.schema import init_automations_db
from app.automations.router import router as automations_router
from app.automations.router import webhook_router as automations_webhook_router
from app.calendar.db import init_calendar_db
from app.calendar.router import router as calendar_router
from app.core.config import settings

logger = logging.getLogger("api")

# --- Fase 0.1: fail-fast se l'auth non è configurata ---
settings.validate_security()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_automations_db()
    except Exception as _e:
        logger.warning(f"Inizializzazione automations_db differita/fallita: {_e}")

    try:
        init_calendar_db()
    except Exception as _e:
        logger.warning(f"Inizializzazione calendar_db differita/fallita: {_e}")

    if settings.enable_automation_scheduler:
        try:
            from app.automations.scheduler import get_scheduler
            scheduler = get_scheduler()
            scheduler.start()
            logger.info("Automation scheduler avviato con successo.")
        except Exception as _e:
            logger.warning(f"Avvio scheduler automazioni fallito: {_e}")

    yield

    # Shutdown
    try:
        from app.automations.scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.stop()
        logger.info("Automation scheduler arrestato.")
    except Exception:
        pass


api = FastAPI(
    title="Home Lab Agent API",
    description="FastAPI service exposing LangGraph Agent with MetaMCP tools, Letta persistent memory, and SQLite Checkpointing",
    version="1.0",
    lifespan=lifespan,
)

# --- Fase 0.1: CORS ristretto alle origini configurate ---
api.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api.state.limiter = limiter
api.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

for module in (system, providers, chat, uploads, kb, threads, approvals, memory):
    api.include_router(module.router)
api.include_router(automations_webhook_router)
api.include_router(automations_router)
api.include_router(calendar_router)
