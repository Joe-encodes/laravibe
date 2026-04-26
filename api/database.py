"""
api/database.py — Async SQLAlchemy setup with aiosqlite.
Creates tables on startup. Use get_db() as FastAPI dependency.
"""
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from api.config import get_settings

settings = get_settings()

# Ensure the data/ directory exists before SQLite tries to create the file
Path("data").mkdir(exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


async def create_tables() -> None:
    """Create all tables and apply any additive schema migrations.
    Called once at FastAPI startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe additive migrations: add columns that may not exist in older DBs.
        # SQLite does not support IF NOT EXISTS on ALTER TABLE, so we catch the error.
        migrations = [
            "ALTER TABLE iterations ADD COLUMN ai_model_used VARCHAR(100)",
            "ALTER TABLE repair_summaries ADD COLUMN what_did_not_work TEXT",
        ]
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # Column already exists — safe to ignore


async def get_db():
    """FastAPI dependency: yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
