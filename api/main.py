"""
api/main.py — FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api.limiter import limiter

from api.config import get_settings
from api.database import create_tables
from api.routers.health import router as health_router
from api.routers.repair import router as repair_router
from api.routers.history import router as history_router
from api.routers.evaluate import router as evaluate_router
from api.routers.stats import router as stats_router
from api.routers.admin import router as admin_router
from api.logging_config import setup_logging

settings = get_settings()

# Initialize unified logging (Console + File)
setup_logging(debug=settings.debug)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup/shutdown tasks."""
    logger.info("Starting up — creating DB tables if needed...")
    try:
        await create_tables()
        logger.info("DB ready.")
    except Exception as exc:
        logger.critical(f"Database initialization failed: {exc}", exc_info=True)
        print(f"FATAL: Could not initialize database: {exc}", file=sys.stderr)
        sys.exit(1)
    yield
    logger.info("Shutting down — goodbye.")

app = FastAPI(
    title="Laravel AI Repair Platform",
    description=(
        "Submit broken PHP/Laravel REST API code, watch it get repaired "
        "iteratively via LLM + Laravel Boost context, validated with Pest + mutation testing."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(repair_router)
app.include_router(history_router)
app.include_router(evaluate_router)
app.include_router(stats_router)
app.include_router(admin_router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Laravel AI Repair Platform — see /docs"}
