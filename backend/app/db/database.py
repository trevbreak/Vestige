from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings
import os

settings = get_settings()

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


def _run_migrations() -> None:
    """Apply any pending Alembic migrations synchronously."""
    try:
        from pathlib import Path
        from alembic.config import Config
        from alembic import command as alembic_command

        alembic_cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        alembic_command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        import structlog
        structlog.get_logger().warning("db.migration_failed", error=str(exc))


async def init_db():
    """Apply migrations and create any missing tables."""
    import asyncio
    from app.models import avatar, session, transcript, memory  # noqa: F401
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
