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

from api.services import docker_service

logger = logging.getLogger(__name__)

# Simple in-process cache: key -> BoostContext JSON string
_cache: dict[str, str] = {}


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


def _cache_key(error_text: str, framework_version: str = "laravel-12") -> str:
    """Copilot: cache by (framework_version, error_signature_hash)."""
    sig = hashlib.sha256(f"{framework_version}:{error_text[:500]}".encode()).hexdigest()
    return sig


async def query_context(container, error_text: str) -> str:
    """
    Query Boost inside the running container for schema + docs context.
    Returns a JSON string (stored in DB) and is also cached in-process.
    Gracefully falls back to empty context if Boost commands fail.
    """
    cache_key = _cache_key(error_text)
    if cache_key in _cache:
        logger.debug("[Boost] Cache hit")
        return _cache[cache_key]

    context = await _fetch_boost_context(container, error_text)
    result_json = context.to_json()
    _cache[cache_key] = result_json
    return result_json


async def _fetch_boost_context(container, error_text: str) -> BoostContext:
    """Run Boost artisan commands inside the container."""

    # 1. Get schema info (using native Laravel 12 command)
    schema_result = await docker_service.execute(
        container,
        "php artisan db:show --json 2>&1",
        timeout=60,
    )
    schema_info = schema_result.stdout.strip() if schema_result.exit_code == 0 else ""

    # 2. Get API Routes (using native Laravel 12 command)
    # This replaces boost:docs with real project routing context
    routes_result = await docker_service.execute(
        container,
        "php artisan route:list --json 2>&1",
        timeout=60,
    )
    routes_raw = routes_result.stdout.strip() if routes_result.exit_code == 0 else ""
    # We store the raw JSON for the AI to parse
    docs_excerpts = [routes_raw] if routes_raw else []


    # 3. Detect component type from error
    component_type = _detect_component_type(error_text)

    if not schema_info and not docs_excerpts:
        logger.warning("[Boost] Both commands returned empty — using fallback context")
        return BoostContext.empty()

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
