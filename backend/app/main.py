import sys
sys.setrecursionlimit(5000)  # Python 3.13 + rich/coqui import chains need headroom

# Configure logging before any other imports touch structlog
from app.logging_config import configure_logging
configure_logging()

import traceback
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db.database import init_db
from app.routers import avatars, sessions, transcripts, health, websocket, pipeline, memory, combat
from app.routers import settings as settings_router
from app.routers import system as system_router
from app.routers import audio_ws
from app.routers import prompts as prompts_router
from app.routers import traits as traits_router
from app.startup_checks import run_startup_checks
from app.tracing import init_tracing

log = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup.begin")
    if settings.debug_mode:
        log.warning("startup.debug_mode_enabled — verbose logging is ON")
    init_tracing()
    await init_db()
    log.info("startup.db_ready")
    await run_startup_checks()
    yield
    log.info("shutdown")
    from app.services.pipeline_manager import pipeline_manager
    await pipeline_manager.stop_all()


app = FastAPI(
    title="Vestige — DnD AI Avatar System",
    description="Locally-hosted AI avatars for absent D&D players.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for portraits and voice samples
import os
os.makedirs("data/uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="data/uploads"), name="uploads")

# ── Debug: log full tracebacks for unhandled 500s ─────────────────────────
if settings.debug_mode:
    @app.exception_handler(Exception)
    async def debug_exception_handler(request: Request, exc: Exception):
        tb = traceback.format_exc()
        log.error(
            "unhandled_exception",
            method=request.method,
            url=str(request.url),
            exc_type=type(exc).__name__,
            traceback=tb,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "traceback": tb},
        )

# Routers
app.include_router(health.router)
app.include_router(avatars.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(transcripts.router, prefix="/api")
app.include_router(websocket.router)
app.include_router(pipeline.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(combat.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(system_router.router, prefix="/api")
app.include_router(audio_ws.router)
app.include_router(prompts_router.router, prefix="/api")
app.include_router(traits_router.router, prefix="/api")
