"""
api/main.py — FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.database import create_tables
from api.routers import health, repair, history, evaluate

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup/shutdown tasks."""
    logger.info("Starting up — creating DB tables if needed...")
    await create_tables()
    logger.info("DB ready.")
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

# ── CORS (allow frontend served from file:// or localhost) ────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(repair.router)
app.include_router(history.router)
app.include_router(evaluate.router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Laravel AI Repair Platform — see /docs"}
