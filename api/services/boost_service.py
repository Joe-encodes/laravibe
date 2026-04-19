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


def _cache_key(submission_id: str, error_text: str, framework_version: str = "laravel-12") -> str:
    """Cache keyed by (submission_id, framework_version, error_signature_hash) to prevent
    cross-submission contamination in batch runs."""
    sig = hashlib.sha256(f"{submission_id}:{framework_version}:{error_text[:500]}".encode()).hexdigest()
    return sig


async def query_context(container, error_text: str, submission_id: str = "global") -> str:
    """
    Query Boost inside the running container for schema + docs context.
    Returns a JSON string (stored in DB) and is also cached in-process.
    Gracefully falls back to empty context if Boost commands fail.
    The cache is scoped by submission_id to prevent cross-session contamination
    during batch evaluation runs.
    """
    cache_key = _cache_key(submission_id, error_text)
    if cache_key in _cache:
        logger.debug("[Boost] Cache hit")
        return _cache[cache_key]

    context = await _fetch_boost_context(container, error_text)
    result_json = context.to_json()
    _cache[cache_key] = result_json
    return result_json


async def _fetch_boost_context(container, error_text: str) -> BoostContext:
    """Run Boost artisan commands inside the container.

    Priority order:
      1. boost:schema (Laravel Boost package) → fallback to db:show (native Laravel)
      2. boost:docs   (Laravel Boost package) → fallback to route:list (native Laravel)
      3. Raw routes/api.php content (always appended so AI sees registered routes)
    """

    # ── 1. Schema context ────────────────────────────────────────────────
    schema_info = ""

    # Try boost:schema first (richer output: tables + columns + types)
    boost_schema = await docker_service.execute(
        container,
        "cd /var/www/sandbox && php artisan boost:schema --format=json 2>&1",
        timeout=60,
    )
    if boost_schema.exit_code == 0 and boost_schema.stdout.strip():
        schema_info = boost_schema.stdout.strip()
        logger.info("[Boost] boost:schema succeeded")
    else:
        # Fallback to native db:show
        logger.info(f"[Boost] boost:schema unavailable (exit={boost_schema.exit_code}), falling back to db:show")
        db_show = await docker_service.execute(
            container,
            "cd /var/www/sandbox && php artisan db:show --json 2>&1",
            timeout=60,
        )
        if db_show.exit_code == 0 and db_show.stdout.strip():
            schema_info = db_show.stdout.strip()
        else:
            logger.warning(f"[Boost] db:show also failed (exit={db_show.exit_code}): {db_show.stdout[:200]}")

    # ── 2. Docs / routing context ────────────────────────────────────────
    docs_excerpts: list[str] = []
    component_type = _detect_component_type(error_text)

    # Try boost:docs first (returns relevant framework docs for the component type)
    boost_docs = await docker_service.execute(
        container,
        f"cd /var/www/sandbox && php artisan boost:docs --query={component_type} --limit=3 2>&1",
        timeout=60,
    )
    if boost_docs.exit_code == 0 and boost_docs.stdout.strip():
        docs_excerpts.append(boost_docs.stdout.strip())
        logger.info("[Boost] boost:docs succeeded")
    else:
        logger.info(f"[Boost] boost:docs unavailable (exit={boost_docs.exit_code}), falling back to route:list")

    # Always fetch route:list as supplementary context (AI needs to see registered routes)
    routes_result = await docker_service.execute(
        container,
        "cd /var/www/sandbox && php artisan route:list --json 2>&1",
        timeout=60,
    )
    if routes_result.exit_code == 0 and routes_result.stdout.strip():
        docs_excerpts.append(routes_result.stdout.strip())
    else:
        logger.warning(f"[Boost] route:list failed (exit={routes_result.exit_code}): {routes_result.stdout[:200]}")

    # 2b. Raw routes/api.php content so AI sees exactly what routes exist
    routes_file_result = await docker_service.execute(
        container,
        "cat /var/www/sandbox/routes/api.php 2>/dev/null",
        timeout=10,
    )
    if routes_file_result.exit_code == 0 and routes_file_result.stdout.strip():
        docs_excerpts.append(f"## routes/api.php (current content)\n{routes_file_result.stdout.strip()[:3000]}")

    # ── 3. Fallback: list model files if no schema ────────────────────────
    if not schema_info:
        model_files = await docker_service.execute(
            container,
            "find app/Models -name '*.php' 2>/dev/null | xargs -n1 basename | sed 's/.php//'",
            timeout=10,
        )
        if model_files.exit_code == 0 and model_files.stdout.strip():
            schema_info = "No database schema found, but these models were detected:\n- " + \
                          model_files.stdout.strip().replace("\n", "\n- ")

    if not schema_info and not docs_excerpts:
        logger.warning("[Boost] All context commands failed — using fallback context")
        return BoostContext.empty()

    return BoostContext(
        schema_info=schema_info,
        docs_excerpts=docs_excerpts,
        component_type=component_type,
    )


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
