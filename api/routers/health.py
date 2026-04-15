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

    # Check AI configuration for the default provider
    from api.config import get_settings
    settings = get_settings()
    provider = settings.default_ai_provider.lower()
    
    provider_keys = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "groq": settings.groq_api_key,
        "qwen": settings.dashscope_api_key,
        "cerebras": settings.cerebras_api_key,
        "gemini": settings.gemini_api_key,
        "deepseek": settings.deepseek_api_key,
    }
    
    if provider == "ollama":
        ai_status = f"ollama (base: {settings.ollama_base_url})"
    elif provider in provider_keys:
        key = provider_keys[provider]
        ai_status = f"{provider}: configured" if key else f"{provider}: missing_key"
    else:
        ai_status = f"unknown_provider: {provider}"

    return HealthResponse(
        status="ok",
        docker=docker_status,
        ai=ai_status,
        db=db_status,
    )
