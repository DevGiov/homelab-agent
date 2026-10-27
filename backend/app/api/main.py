from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import startup
from app.api.deps import limiter
from app.api.routes import approvals, chat, kb, memory, providers, system, threads, uploads
from app.automations.routes import router as automations_router
from app.automations.routes import webhook_router as automations_webhook_router
from app.calendar.router import router as calendar_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup.start()
    yield
    startup.stop()


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
