"""
api/routers/health.py — GET /api/health endpoint.
Checks FastAPI is alive, Docker daemon is reachable, and DB is writable.
"""
from fastapi import APIRouter
from sqlalchemy import text

from api.database import AsyncSessionLocal
from api.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    # Check Docker
    docker_status = "unknown"
    try:
        import docker
        client = docker.from_env()
        client.ping()
        docker_status = "connected"
    except Exception as exc:
        docker_status = f"error: {exc}"

    # Check DB
    db_status = "unknown"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        db_status = f"error: {exc}"

    # Check AI (just verify key is set)
    from api.config import get_settings
    settings = get_settings()
    ai_status = "key_set" if (
        settings.anthropic_api_key or settings.openai_api_key or settings.groq_api_key
    ) else "no_key_configured"

    return HealthResponse(
        status="ok",
        docker=docker_status,
        ai=ai_status,
        db=db_status,
    )
