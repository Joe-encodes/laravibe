"""
api/services/boost_service.py — Query Laravel Boost inside a running sandbox container.
Caches context by (submission_id, component_type) to avoid redundant Docker exec calls.
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

    # Tables we always skip — they're present on every fresh Laravel install
    # and carry zero signal for the repair AI.
    _NOISE_TABLES = frozenset({
        "cache", "cache_locks", "failed_jobs", "job_batches", "jobs",
        "migrations", "password_reset_tokens", "sessions",
    })

    # Internal Laravel/Boost routes that waste tokens with no repair value
    _NOISE_ROUTE_NAMES = frozenset({
        "boost.browser-logs", "sanctum.csrf-cookie",
        "storage.local", "storage.local.upload",
        "generated::q40m02NKXo0PsxAY", "generated::wQn8ABLpjElQZ9Aw",
    })

    def to_prompt_text(self) -> str:
        parts = []

        if self.schema_info:
            try:
                schema_data = json.loads(self.schema_info)
                app_tables = [
                    t for t in schema_data.get("tables", [])
                    if t.get("table") not in BoostContext._NOISE_TABLES
                ]
                if app_tables:
                    table_lines = ", ".join(
                        f"{t['table']} ({', '.join(c['name'] for c in t.get('columns', []))})"
                        if t.get('columns') else t['table']
                        for t in app_tables
                    )
                    parts.append(f"## App Tables\n{table_lines}")
            except (json.JSONDecodeError, TypeError):
                if self.schema_info and self.schema_info != "No schema info available.":
                    parts.append(f"## Schema\n{self.schema_info}")

        if self.docs_excerpts:
            filtered_routes = []
            for excerpt in self.docs_excerpts:
                try:
                    routes = json.loads(excerpt) if isinstance(excerpt, str) else excerpt
                    if isinstance(routes, list):
                        app_routes = [
                            r for r in routes
                            if r.get("name") not in BoostContext._NOISE_ROUTE_NAMES
                            and not (r.get("uri", "").startswith("_boost"))
                            and not (r.get("uri", "").startswith("storage"))
                            and not (r.get("uri", "").startswith("sanctum"))
                        ]
                        for r in app_routes:
                            filtered_routes.append(
                                f"  {r.get('method','?')} /{r.get('uri','?')} "
                                f"→ {r.get('action','?')}"
                            )
                    else:
                        filtered_routes.append(str(excerpt))
                except (json.JSONDecodeError, TypeError):
                    filtered_routes.append(str(excerpt))

            if filtered_routes:
                parts.append("## Registered Routes\n" + "\n".join(filtered_routes))

        if self.component_type and self.component_type != "unknown":
            parts.append(f"## Component: {self.component_type}")

        return "\n\n".join(parts) if parts else ""


def _cache_key(submission_id: str, error_text: str, framework_version: str = "laravel-12") -> str:
    """Cache keyed by (submission_id, component_type, framework_version).

    Using component_type (not the full error text) means that if two different
    iterations in the same submission both fail on a 'model' error, we hit the
    cache on the second call instead of re-executing boost:schema inside Docker.
    """
    component_type = _detect_component_type(error_text)
    sig = hashlib.sha256(
        f"{submission_id}:{framework_version}:{component_type}".encode()
    ).hexdigest()
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
    """
    Score-based component type detection.

    Uses a scoring dict instead of an if/elif priority chain to handle
    stack traces that mention multiple component types (e.g. a controller
    error caused by a missing model would contain both 'controller' and 'model').
    The component with the highest score wins; ties go to the more specific type.
    """
    text = error_text.lower()

    scores: dict[str, int] = {
        "controller": 0,
        "model": 0,
        "migration": 0,
        "middleware": 0,
        "route": 0,
        "request": 0,
    }

    # Controller keywords
    if "controller" in text:       scores["controller"] += 1
    if "http/controllers" in text: scores["controller"] += 2

    # Model keywords — weighted higher because 'Class X not found' always means a dep issue
    if "model" in text:            scores["model"] += 1
    if "eloquent" in text:         scores["model"] += 2
    if "app\\models" in text:      scores["model"] += 3
    if "class\"" in text and "not found" in text: scores["model"] += 2

    # Migration keywords
    if "migration" in text:        scores["migration"] += 2
    if "schema" in text:           scores["migration"] += 1
    if "no such table" in text:    scores["migration"] += 3

    # Middleware
    if "middleware" in text:        scores["middleware"] += 2

    # Route
    if "route" in text:             scores["route"] += 1
    if "routenotfound" in text:     scores["route"] += 3

    # Form request / validation
    if "request" in text or "validation" in text: scores["request"] += 1
    if "formrequest" in text:                      scores["request"] += 2

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "unknown"
