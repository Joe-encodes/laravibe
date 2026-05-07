"""
api/database.py — Async SQLAlchemy setup.
Supports both SQLite (local) and PostgreSQL (production).
Creates tables on startup. Use get_db() as FastAPI dependency.
"""
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event

from api.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# Engine and session factory are created lazily, so importing this module
# (e.g. in tests) does not fail if .env is not loaded yet.
_engine = None
_sessionmaker: Optional[async_sessionmaker] = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = settings.database_url
        
        is_sqlite = db_url.startswith("sqlite")
        
        # SQLite specific args
        connect_args = {}
        if is_sqlite:
            Path("data").mkdir(exist_ok=True)
            connect_args = {"check_same_thread": False, "timeout": 30}
            
        _engine = create_async_engine(
            db_url,
            echo=settings.debug,
            connect_args=connect_args,
        )
        
        if is_sqlite:
            @event.listens_for(_engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA synchronous = NORMAL;")
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.close()
            
    return _engine


def get_sessionmaker():
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _sessionmaker


def AsyncSessionLocal():
    """Compatibility helper to return a new session from the sessionmaker."""
    return get_sessionmaker()()


async def create_tables() -> None:
    """Create all tables and apply any additive schema migrations.
    Called once at FastAPI startup.
    """
    from sqlalchemy import text

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Additive columns for older DBs (ignore if already present)
        migrations = [
            "ALTER TABLE iterations ADD COLUMN ai_model_used VARCHAR(100)",
            "ALTER TABLE repair_summaries ADD COLUMN what_did_not_work TEXT",
            "ALTER TABLE iterations ADD COLUMN planner_model VARCHAR(100)",
            "ALTER TABLE iterations ADD COLUMN executor_model VARCHAR(100)",
            "ALTER TABLE iterations ADD COLUMN reviewer_model VARCHAR(100)",
            "ALTER TABLE iterations ADD COLUMN failure_reason VARCHAR(100)",
            "ALTER TABLE iterations ADD COLUMN failure_details TEXT",
            "ALTER TABLE iterations ADD COLUMN pm_category VARCHAR(50)",
            "ALTER TABLE iterations ADD COLUMN pm_strategy TEXT",
            "ALTER TABLE iterations ADD COLUMN pipeline_logs TEXT",
            "ALTER TABLE submissions ADD COLUMN is_cancelled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE submissions ADD COLUMN container_id VARCHAR(64)",
        ]
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # column already exists


async def get_db():
    """FastAPI dependency: yields an async DB session."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            # Only commit if there are actual changes to persist
            if session.new or session.deleted or session.dirty:
                await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
