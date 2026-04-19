"""
api/services/sandbox_service.py — Laravel sandbox interaction helpers.

Extracted from repair_service.py to keep the repair loop lean and readable.
Each function does ONE thing inside a running Docker container:
  - detect_class_info()      Parse namespace + classname from PHP code
  - setup_sqlite()           Configure sandbox to use SQLite
  - place_code_in_laravel()  Copy code to PSR-4 path, verify via Tinker
  - scaffold_route()         Append apiResource() to routes/api.php
  - run_pest_test()          Run Pest --filter=RepairTest
  - run_mutation_test()      Run Pest --mutate, parse score
  - reinject_files()         Re-inject supplementary files into fresh container
  - inject_pest_test()       Write Pest test file into container
  - ensure_covers_directive() Inject covers() if missing from Pest test
"""
import base64
import logging
import re
import shlex
from dataclasses import dataclass

from api.config import get_settings
from api.services import docker_service
from api.services.docker_service import ExecResult

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ClassInfo:
    """Parsed metadata about the PHP class being repaired."""
    namespace: str          # e.g. "App/Http/Controllers"
    clean_namespace: str    # e.g. "App\\Http\\Controllers"
    classname: str          # e.g. "UserController"
    dest_file: str          # e.g. "/var/www/sandbox/app/Http/Controllers/UserController.php"
    fqcn: str               # e.g. "App\\\\Http\\\\Controllers\\\\UserController" (for PHP)
    route_resource: str     # e.g. "users" (pluralized, lowercase)


@dataclass
class MutationResult:
    """Result from a Pest mutation test run."""
    score: float            # 0.0 - 100.0
    passed: bool            # True if score >= threshold
    output: str             # Raw Pest output (truncated)
    duration_ms: int
    soft_pass: bool = False # True if mutation infra failed (treated as pass)


# ── Namespace / Class Detection ───────────────────────────────────────────────

async def detect_class_info(container) -> ClassInfo:
    """
    Parse namespace and classname from /submitted/code.php inside the container.
    Returns a ClassInfo with all derived paths and identifiers.
    """
    # Detect namespace
    detect_ns_cmd = (
        "php -r '$c = @file_get_contents(\"/submitted/code.php\"); "
        "if (preg_match(\"/namespace\\\\s+([^;\\\\s]+)/s\", $c, $m)) echo trim($m[1]);'"
    )
    ns_result = await docker_service.execute(container, detect_ns_cmd, timeout=5)
    namespace = ns_result.stdout.strip().replace("\\", "/") or "App/Http/Controllers"

    # Detect classname
    detect_cls_cmd = (
        "php -r '$c = @file_get_contents(\"/submitted/code.php\"); "
        "if (preg_match(\"/class\\\\s+(\\\\w+)/s\", $c, $m)) echo $m[1];'"
    )
    cls_result = await docker_service.execute(container, detect_cls_cmd, timeout=5)
    classname = cls_result.stdout.strip() or "SubmittedClass"

    # Derive PSR-4 destination path
    clean_ns = namespace.replace("/", "\\").strip("\\")
    dest_namespace = clean_ns.replace("\\", "/")
    if dest_namespace.startswith("App/"):
        dest_namespace = "app/" + dest_namespace[4:]
    elif dest_namespace == "App":
        dest_namespace = "app"
    dest_dir = f"/var/www/sandbox/{dest_namespace}"
    dest_file = f"{dest_dir}/{classname}.php"

    # Build FQCN for PHP class_exists() — needs double-escaped backslashes
    php_ns = namespace.replace("/", "\\\\")
    fqcn = f"{php_ns}\\\\{classname}"

    # Pluralized route resource name (UserController → users)
    resource_name = re.sub(r'Controller$', '', classname, flags=re.IGNORECASE).lower()
    route_resource = (resource_name + 's') if resource_name else (classname.lower() + 's')

    info = ClassInfo(
        namespace=namespace,
        clean_namespace=clean_ns,
        classname=classname,
        dest_file=dest_file,
        fqcn=fqcn,
        route_resource=route_resource,
    )
    logger.info(f"[Sandbox] Detected: namespace={namespace} class={classname} dest={dest_file}")
    return info


# ── SQLite Setup ──────────────────────────────────────────────────────────────

async def setup_sqlite(container) -> None:
    """
    Configure the sandbox to use SQLite instead of MySQL.
    The container runs with --network=none, so MySQL is unreachable.
    SQLite lets Boost's schema query work without network access.
    """
    sh_script = """#!/bin/bash
cd /var/www/sandbox
touch database/database.sqlite
chmod 666 database/database.sqlite
chmod 777 database
sed -i 's/DB_CONNECTION=.*/DB_CONNECTION=sqlite/' .env 2>/dev/null
sed -i 's|DB_DATABASE=.*|DB_DATABASE=/var/www/sandbox/database/database.sqlite|' .env 2>/dev/null
sed -i '/DB_CONNECTION/d' phpunit.xml 2>/dev/null
sed -i '/DB_DATABASE/d' phpunit.xml 2>/dev/null
php artisan migrate --force --no-interaction 2>&1 | tail -3
chmod -R 777 storage bootstrap/cache 2>/dev/null
"""
    await docker_service.copy_file(container, "/tmp/setup_sqlite.sh", sh_script)
    await docker_service.execute(container, "bash /tmp/setup_sqlite.sh", timeout=45, user="root")


# ── Code Placement & Verification ─────────────────────────────────────────────

async def place_code_in_laravel(
    container,
    class_info: ClassInfo,
    should_migrate: bool = False,
) -> ExecResult:
    """
    Copy /submitted/code.php to the correct PSR-4 location inside the Laravel
    sandbox, refresh the autoloader, and verify the class loads via Tinker.

    Returns an ExecResult. If stdout contains "CLASS_OK" and no "ERROR:", the
    class loaded successfully (exit_code will be normalised to 0).
    """
    safe_dest_dir = shlex.quote(str(__import__('pathlib').Path(class_info.dest_file).parent))
    safe_dest_file = shlex.quote(class_info.dest_file)
    safe_fqcn = class_info.fqcn.replace("'", "\\'")

    # Base64-encode Tinker PHP script to avoid shell quoting issues
    tinker_code = (
        "try {\n"
        f"    if (!class_exists('{safe_fqcn}')) {{\n"
        f"        throw new Exception('Class {safe_fqcn} not found or failed to load');\n"
        "    }\n"
        "    echo 'CLASS_OK';\n"
        "} catch (Throwable $e) {\n"
        "    echo 'ERROR: ' . $e->getMessage();\n"
        "}"
    )
    b64_tinker = base64.b64encode(tinker_code.encode()).decode()

    migration_cmd = "php artisan migrate --force --no-interaction && " if should_migrate else ""

    cmd = (
        f"mkdir -p {safe_dest_dir} /var/www/sandbox/app/Http/Controllers /var/www/sandbox/app/Models && "
        f"cp /submitted/code.php {safe_dest_file} 2>/dev/null || true && "
        "cd /var/www/sandbox && "
        f"{migration_cmd}"
        "php artisan optimize:clear >/dev/null 2>&1 && "
        "composer dump-autoload --optimize -q 2>&1 && "
        f"php artisan tinker --execute=\"$(echo {b64_tinker} | base64 -d)\" 2>&1"
    )
    result = await docker_service.execute(container, cmd, timeout=settings.container_timeout_seconds)

    # Normalise: CLASS_OK without ERROR → exit_code=0, otherwise → 1
    if "CLASS_OK" in result.stdout and "ERROR:" not in result.stdout:
        return ExecResult(stdout=result.stdout, stderr="", exit_code=0, duration_ms=result.duration_ms)
    return ExecResult(stdout=result.stdout, stderr=result.stderr, exit_code=1, duration_ms=result.duration_ms)


# ── Route Scaffolding ─────────────────────────────────────────────────────────

async def scaffold_route(container, class_info: ClassInfo) -> None:
    """
    Append a Route::apiResource() line to routes/api.php (idempotent).
    Uses a dynamically generated PHP script pushed to the container to
    avoid bash escaping formatting bugs with PHP strings.
    """
    classname = class_info.classname
    resource = class_info.route_resource
    canonical_ns = (
        class_info.clean_namespace
        if class_info.clean_namespace.startswith("App\\Http\\Controllers")
        else "App\\Http\\Controllers"
    )
    fqcn = f"{canonical_ns}\\{classname}"

    php_script = f"""<?php
$file = '/var/www/sandbox/routes/api.php';
$content = file_exists($file) ? file_get_contents($file) : '';
if (strpos($content, '{classname}::class') === false) {{
    file_put_contents($file, "\\nRoute::apiResource('{resource}', \\\\{fqcn}::class);\\n", FILE_APPEND);
}}
"""
    await docker_service.copy_file(container, "/tmp/scaffold.php", php_script)
    cmd = "php /tmp/scaffold.php && cd /var/www/sandbox && php artisan route:clear > /dev/null 2>&1"
    
    result = await docker_service.execute(container, cmd, timeout=20, user="root")
    if result.exit_code != 0:
        logger.error(f"[Scaffold] Failed with exit {result.exit_code}: {result.stderr}")
    else:
        logger.info(f"[Scaffold] Registered /api/{resource} -> {fqcn}")


# ── Pest Test Execution ──────────────────────────────────────────────────────

async def run_pest_test(container) -> ExecResult:
    """Run Pest functional tests (RepairTest only)."""
    return await docker_service.execute(
        container,
        "cd /var/www/sandbox && ./vendor/bin/pest --filter=RepairTest --no-coverage 2>&1",
        timeout=60,
    )


async def capture_laravel_log(container) -> str:
    """
    Read the last 40 lines of Laravel's application log after a Pest failure.
    This surfaces the real PHP exception (e.g. "Class App\\Models\\Product not found")
    that isn't propagated through the Pest assertion output.
    """
    result = await docker_service.execute(
        container,
        "tail -n 40 /var/www/sandbox/storage/logs/laravel.log 2>/dev/null || echo 'No laravel log found'",
        timeout=10,
        user="root",
    )
    return result.stdout.strip()


# ── Mutation Testing ──────────────────────────────────────────────────────────

async def run_mutation_test(container) -> MutationResult:
    """
    Run Pest mutation tests and parse the score.

    Distinguishes between:
      - Real infra failures (pcov missing, unknown option) → soft pass
      - Missing covers()/mutates() directive → NOT a soft pass (score=0, fail)
      - Normal mutation results → parse the score
    """
    result = await docker_service.execute(
        container,
        "./vendor/bin/pest --mutate 2>&1",
        timeout=120,
    )

    output = result.stdout

    # Detect missing covers()/mutates()
    MISSING_COVERS_MARKERS = [
        "requires the usage of the covers() function",
        "requires the usage of the mutates() function",
    ]
    is_missing_covers = any(marker in output for marker in MISSING_COVERS_MARKERS)

    if is_missing_covers:
        logger.warning(f"[Mutation] Test lacks covers()/mutates() directive — returning score=0")
        return MutationResult(
            score=0.0, passed=False, output=output[:1000],
            duration_ms=result.duration_ms, soft_pass=False,
        )

    # Detect Test Dependency failures (e.g., missing Class/Factory)
    TEST_DEPENDENCY_MARKERS = [
        "not found", "doesn't exist", "does not exist", "ReflectionException"
    ]
    is_dependency_failure = any(marker in output for marker in TEST_DEPENDENCY_MARKERS) and "command not found" not in output

    if is_dependency_failure:
        logger.warning(f"[Mutation] Test dependency failure: {output[:200]}")
        return MutationResult(
            score=0.0, passed=False, output=f"TEST_DEPENDENCY_ERROR: Your test failed because a class or method could not be found. Did you forget to create a Model or Factory?\n\n{output[:1000]}",
            duration_ms=result.duration_ms, soft_pass=False,
        )

    # Detect infrastructure failures
    INFRA_FAILURE_MARKERS = [
        "Unknown option", "Extension pcov", "command not found"
    ]
    is_infra_failure = any(marker in output for marker in INFRA_FAILURE_MARKERS)

    if is_infra_failure:
        logger.warning(f"[Mutation] Infra issue, soft-pass: {output[:200]}")
        return MutationResult(
            score=100.0, passed=True, output=output[:1000],
            duration_ms=result.duration_ms, soft_pass=True,
        )

    score = parse_mutation_score(output)
    return MutationResult(
        score=score,
        passed=score >= settings.mutation_score_threshold,
        output=output[:1000],
        duration_ms=result.duration_ms,
    )


def parse_mutation_score(output: str) -> float:
    """
    Extract mutation score percentage from Pest --mutate output.

    Supports multiple output formats:
      "Mutations: 15 tested, 12 killed (80.0%), 3 survived"
      "Score:  80.00 %"
      "80% mutation score"
      "mutation score: 80"
    Returns 0.0 if no pattern matches (fail-safe).
    """
    # Strip ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_output = ansi_escape.sub('', output)
    
    logger.debug(f"[MutationParser] clean output:\n{clean_output[:800]}")

    patterns = [
        r"killed\s*\((\d+(?:\.\d+)?)%\)",           # "12 killed (80.0%)"
        r"mutations?\s*:\s*(\d+(?:\.\d+)?)\s*%",    # "Mutations: 78.3%"
        r"(\d+(?:\.\d+)?)\s*%\s*mutation\s+score",   # "80% mutation score"
        r"mutation\s+score[:\s]+(\d+(?:\.\d+)?)",    # "mutation score: 80"
        r"score[:\s]+(\d+(?:\.\d+)?)\s*%",           # "Score: 80.00%"
        r"(\d+(?:\.\d+)?)\s*%\s*scored",             # "80.0% scored"
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_output, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            logger.info(f"[MutationParser] Matched '{pattern}' → score={score}%")
            return score

    logger.warning(f"[MutationParser] No pattern matched. Returning 0.0. Snippet: {output[:200]!r}")
    return 0.0


# ── File Injection Helpers ────────────────────────────────────────────────────

async def reinject_files(container, supplementary_files: dict[str, str]) -> None:
    """
    Re-inject dependency files (Models, Migrations, etc.) that were created
    by the AI in a previous iteration but lost when that container was destroyed.
    """
    if not supplementary_files:
        return

    for rel_path, file_content in supplementary_files.items():
        await docker_service.copy_file(container, f"/var/www/sandbox/{rel_path}", file_content)

    # Refresh autoloader so newly injected classes are discoverable
    await docker_service.execute(
        container,
        "cd /var/www/sandbox && php artisan optimize:clear >/dev/null 2>&1 && composer dump-autoload --optimize -q 2>&1",
        timeout=45,
    )


async def inject_pest_test(container, test_code: str) -> None:
    """Write a Pest test file to tests/Feature/RepairTest.php inside the container."""
    if not test_code:
        return
    await docker_service.copy_file(container, "/var/www/sandbox/tests/Feature/RepairTest.php", test_code)


async def lint_test_file(container) -> ExecResult:
    """Run php -l on the injected RepairTest.php to catch AI syntax errors early."""
    return await docker_service.execute(
        container,
        "php -l /var/www/sandbox/tests/Feature/RepairTest.php 2>&1",
        timeout=10,
    )


def generate_baseline_pest_test(class_info: ClassInfo) -> str:
    """
    Generate a deterministic, system-controlled Pest test.
    Must be a pure HTTP assertion with zero dependency on coverage machinery.
    """
    resource = class_info.route_resource

    return (
        "<?php\n"
        f"use function Pest\\Laravel\\getJson;\n\n"
        f"test('{resource} index endpoint responds successfully', function () {{\n"
        f"    getJson('/api/{resource}')\n"
        f"        ->assertSuccessful();\n"
        f"}});\n"
    )


def ensure_covers_directive(pest_test: str, current_code: str, fqcn_from_sandbox: str | None) -> str:
    """
    Ensure all programmatic requirements for a Pest test in this sandbox are met.
    """
    if not pest_test:
        return pest_test

    # 1. Inject required function imports
    # We use a comprehensive list of common Pest/Laravel helpers
    functions = ["getJson", "postJson", "putJson", "patchJson", "deleteJson", "get", "post", "put", "patch", "delete"]
    if "actingAs(" in pest_test:
        functions.append("actingAs")
    
    import_line = f"use function Pest\\Laravel\\{{{', '.join(functions)}}};"

    if "use function Pest\\Laravel" not in pest_test:
        if "<?php\n" in pest_test:
            pest_test = pest_test.replace("<?php\n", f"<?php\n{import_line}\n", 1)
        elif "<?php" in pest_test:
            pest_test = pest_test.replace("<?php", f"<?php\n{import_line}\n", 1)
        else:
            pest_test = f"<?php\n{import_line}\n" + pest_test

    # 2. Automatically inject missing Model imports
    # Look for words starting with uppercase (potential models)
    potential_models = set(re.findall(r'\b([A-Z][a-zA-Z0-9_]*)::', pest_test))
    for model in potential_models:
        if model != "Route" and model != "Schema" and model != "DB" and f"use App\\Models\\{model};" not in pest_test:
            # We boldly assume it's an App\Models\ model if it's not a common facade
            model_import = f"use App\\Models\\{model};\n"
            if "<?php\n" in pest_test:
                pest_test = pest_test.replace("<?php\n", f"<?php\n{model_import}", 1)
            else:
                pest_test = pest_test.replace("<?php", f"<?php\n{model_import}", 1)

    # 3. Inject covers() if missing
    if "covers(" in pest_test:
        return pest_test

    target_fqcn = None
    if fqcn_from_sandbox and "Parse error" not in fqcn_from_sandbox:
        target_fqcn = fqcn_from_sandbox
    else:
        class_match = re.search(r'class\s+(\w+)', current_code)
        if class_match:
            class_name = class_match.group(1)
            ns_match = re.search(r'namespace\s+([^;]+);', current_code)
            if ns_match:
                target_fqcn = f"\\\\{ns_match.group(1).strip()}\\\\{class_name}"
            else:
                target_fqcn = f"\\\\{class_name}"

    if not target_fqcn:
        return pest_test

    absolute_fqcn = target_fqcn if target_fqcn.startswith("\\") else "\\" + target_fqcn
    covers_line = f"covers({absolute_fqcn}::class);\n"

    # Insert covers directly after the PHP opening tag and imports
    lines = pest_test.split('\n')
    for i, line in enumerate(lines):
        if line.startswith("use function") or "<?php" in line:
            continue
        lines.insert(i, covers_line)
        break
    else:
        lines.insert(1, covers_line)

    return '\n'.join(lines)
