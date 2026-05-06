"""
api/services/boost_service.py — Query Laravel Boost inside a running sandbox container.

Copilot addition: cache results by (framework_version, error_signature_hash)
to avoid redundant exec calls and reduce cost on repeated errors.
"""
import hashlib
import json
import logging
import shlex
from dataclasses import dataclass, field, asdict

from api.services.sandbox import docker as docker_service
import api.services.sandbox as sandbox

docker = docker_service

logger = logging.getLogger(__name__)

import time

# Simple in-process cache: key -> (BoostContext JSON string, expiry_timestamp)
_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL_SECONDS = 3600


@dataclass
class BoostContext:
    schema_info: str = ""
    docs_excerpts: list[str] = field(default_factory=list)
    component_type: str = "unknown"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def empty(cls) -> "BoostContext":
        return cls(
            schema_info="No schema info available.",
            docs_excerpts=[],
            component_type="unknown",
        )

    def to_prompt_text(self) -> str:
        parts = []
        if self.schema_info:
            parts.append(f"## Relevant Schema\n{self.schema_info}")
        if self.docs_excerpts:
            parts.append("## Laravel Docs Excerpts\n" + "\n---\n".join(self.docs_excerpts))
        if self.component_type and self.component_type != "unknown":
            parts.append(f"## Detected Component Type\n{self.component_type}")
        return "\n\n".join(parts) if parts else "No Boost context available."


def _cache_key(submission_id: str, error_text: str, framework_version: str = "laravel-12") -> str:
    """Cache by (submission_id, framework_version, error_signature_hash)."""
    sig = hashlib.sha256(f"{submission_id}:{framework_version}:{error_text[:500]}".encode()).hexdigest()
    return sig


async def get_boost_context(container_id: str, error_text: str, submission_id: str | None = None) -> str:
    """Compatibility wrapper used by the orchestrator and tests."""
    container = sandbox.get_container(container_id)
    return await query_context(container, error_text, submission_id=submission_id)


async def query_context(container_or_id, error_text: str, submission_id: str | None = None) -> str:
    """
    Query Boost inside the running container for schema + docs context.
    Returns a JSON string (stored in DB) and is also cached in-process.
    Gracefully falls back to empty context if Boost commands fail.
    """
    if isinstance(container_or_id, str):
        container = sandbox.get_container(container_or_id)
    else:
        container = container_or_id

    cache_key = _cache_key(submission_id or "unknown", error_text)
    if cache_key in _cache:
        cached_json, expires_at = _cache[cache_key]
        if time.monotonic() < expires_at:
            logger.debug("[Boost] Cache hit")
            return cached_json
        else:
            del _cache[cache_key]

    context = await _fetch_boost_context(container, error_text)
    result_json = context.to_json()
    _cache[cache_key] = (result_json, time.monotonic() + CACHE_TTL_SECONDS)
    return result_json

async def _fetch_boost_context(container, error_text: str) -> BoostContext:
    """Run Boost artisan commands inside the container."""

    # 1. Query Route List (The application surface area)
    route_result = await docker_service.execute(
        container,
        "php artisan route:list --json --except-vendor 2>&1",
        timeout=20,
    )
    schema_info = ""
    if route_result.exit_code == 0:
        schema_info = f"### ROUTES\n{route_result.stdout.strip()}"
    else:
        # Fallback to simple list if --json fails
        fallback = await docker_service.execute(container, "php artisan route:list --except-vendor")
        stdout = fallback.stdout.strip()
        if stdout:
            schema_info = f"### ROUTES (text)\n{stdout}"
        else:
            schema_info = "No schema info available."

    # 2. Query App Environment/Packages
    about_result = await docker_service.execute(
        container,
        "php artisan about --json 2>&1",
        timeout=20,
    )
    docs_excerpts = []
    if about_result.exit_code == 0:
        docs_excerpts.append(f"### ENVIRONMENT & PACKAGES\n{about_result.stdout.strip()}")
    else:
        # Fallback to model list to show data structure
        fallback = await docker_service.execute(container, "php artisan model:show --all 2>&1")
        if fallback.exit_code == 0:
            docs_excerpts.append(f"### MODELS\n{fallback.stdout.strip()}")

    # 3. Detect component type from error
    component_type = _detect_component_type(error_text)

    return BoostContext(
        schema_info=schema_info,
        docs_excerpts=docs_excerpts,
        component_type=component_type,
    )


def _extract_error_type(error_text: str) -> str:
    """Pull a short error type string for the Boost docs query."""
    lines = error_text.splitlines()
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in ["error:", "exception:", "fatal"]):
            return line.strip()[:120]
    return error_text[:120]


def _detect_component_type(error_text: str) -> str:
    """Heuristic: detect what kind of Laravel component the error relates to."""
    text = error_text.lower()
    if "controller" in text:
        return "controller"
    if "model" in text or "eloquent" in text:
        return "model"
    if "migration" in text or "schema" in text:
        return "migration"
    if "middleware" in text:
        return "middleware"
    if "route" in text:
        return "route"
    if "request" in text or "validation" in text:
        return "form_request"
    return "unknown"
