import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db.database import init_db
from app.routers import avatars, sessions, transcripts, health, websocket

log = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup.begin")
    await init_db()
    log.info("startup.db_ready")
    yield
    log.info("shutdown")


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

# Routers
app.include_router(health.router)
app.include_router(avatars.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(transcripts.router, prefix="/api")
app.include_router(websocket.router)
