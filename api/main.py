"""
api/main.py — FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload --port 8000
"""
import logging
import sys
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from api.limiter import limiter

from api.config import get_settings
from api.database import create_tables
from api.routers.health import router as health_router
from api.routers.auth import router as auth_router
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
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    allow_credentials=True,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(repair_router)
app.include_router(history_router)
app.include_router(evaluate_router)
app.include_router(stats_router)
app.include_router(admin_router)

# ── Static Files (Frontend) ──────────────────────────────────────────────────
# In production, we serve the compiled React app from the /static folder.
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    """
    Serve index.html for all non-API routes (SPA support).
    If a file exists in /static, the mount point above handles it.
    Otherwise, we fall back to index.html for React routing.
    """
    if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("redoc"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
        
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
        
    return {"message": "Laravel AI Repair Platform — API is running. UI not found."}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler: prevents raw Python tracebacks reaching the client.
    Logs the full traceback internally, returns a clean JSON 500 with a
    correlation error_id so the log can be traced.
    """
    error_id = str(uuid.uuid4())[:8]
    logger.error(
        f"[500] Unhandled exception on {request.method} {request.url.path} "
        f"[error_id={error_id}]: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred. The engineering team has been notified.",
            "error_id": error_id,
            "path": str(request.url.path),
        },
    )
