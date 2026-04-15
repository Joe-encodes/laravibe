# Laravel AI Repair Platform — Backend Implementation Checklist
**Source authority:** MANUAL.md · Chapters 1–5 · Literature Review · System Design (Chapter 3)**
**Version:** 1.0 | Adamu Joseph Obinna

> Legend: ✅ Must Have (thesis-critical) · 🔶 Nice to Have (future work / bonus marks)
> Every ✅ item maps to at least one thesis claim, cited work, or system design commitment.
> Tick each box as you verify it works in the running platform.

---

## 1. Docker Sandbox Environment
*Basis: Section 3.2.1, Chapter 4, Bhardwaj & Kumar (2025), Cito et al. (2017), Sultan et al. (2019)*

### 1.1 Image Contents
- [ ] ✅ Base image is `php:8.3-cli-alpine` — matches thesis claim of PHP 8.3
- [ ] ✅ Composer 2.x installed and on PATH
- [ ] ✅ Laravel 12.x installed via `composer create-project laravel/laravel sandbox "12.*"`
- [ ] ✅ Laravel Boost installed as dev dependency: `composer require laravel/boost --dev`
- [ ] ✅ `php artisan boost:install` executed during image build with REST API + Pest API testing skills configured
- [ ] ✅ Pest 3.x installed: `pestphp/pest` + `pestphp/pest-plugin-laravel`
- [ ] ✅ Pest Mutate plugin installed: `pestphp/pest-plugin-mutate`
- [ ] ✅ `pcov` PHP extension installed (required for `pest --mutate --coverage-pcov`)
- [ ] ✅ Redis PHP extension installed (Laravel cache layer)
- [ ] ✅ MySQL 8.0 or PostgreSQL 16 available within image for Eloquent connectivity
- [ ] ✅ `php.ini` configured with appropriate `memory_limit`, `max_execution_time`
- [ ] ✅ `entrypoint.sh` sets up Laravel `.env` with DB credentials on container start
- [ ] ✅ Image builds successfully in ≤ 10 minutes on first run
- [ ] ✅ Subsequent builds use Docker layer cache (Composer install does not re-run if Dockerfile unchanged)

### 1.2 Runtime Security Constraints
*Basis: Bhardwaj & Kumar (2025), Cito et al. (2017), Sultan et al. (2019), Section 4.2.4*
- [ ] ✅ `--network=none` — zero internet access inside containers
- [ ] ✅ `--memory=512m` — memory cap enforced
- [ ] ✅ `--pids-limit=64` — fork bomb prevention
- [ ] ✅ `--security-opt=no-new-privileges:true` — privilege escalation blocked
- [ ] ✅ CPU limited to 0.5 cores: `--nano-cpus` or equivalent
- [ ] ✅ Execution timeout enforced at 90 seconds per iteration (configurable via ENV)
- [ ] ✅ Every container is destroyed inside a `finally` block — zero container leaks
- [ ] ✅ User code is injected via in-memory tar archive — no temp files written to host filesystem
- [ ] ✅ Container runs as non-root user inside image

### 1.3 Code Injection and Execution
- [ ] ✅ Submitted PHP is written to `/submitted/code.php` inside container
- [ ] ✅ PHP namespace and class name detected from submitted code via `grep`
- [ ] ✅ File copied to correct Laravel directory path matching namespace
- [ ] ✅ `composer dump-autoload` run after injection to register class
- [ ] ✅ PHP lint check: `php -l /submitted/code.php` — fastest first gate
- [ ] ✅ Laravel Tinker validation: `php artisan tinker --execute="class_exists(...)"` — runtime resolution check
- [ ] ✅ `CLASS_OK` sentinel string parsed from Tinker output to confirm success
- [ ] ✅ `has_php_fatal` property on ExecResult handles PHP fatal errors that produce zero exit code
- [ ] ✅ `ExecResult` dataclass captures: stdout, stderr, exit_code, duration_ms
- [ ] ✅ Supplementary files dict re-injects files created in prior iterations into every fresh container

---

## 2. FastAPI Coordinator Service
*Basis: Section 3.2.2, Chapter 4, Sharma (2020), Tragura (2023), Marzouki (2025)*

### 2.1 Application Structure
- [ ] ✅ `main.py` — app entry point, lifespan hooks, CORS middleware, router registration
- [ ] ✅ `config.py` — all settings loaded from `.env` via `pydantic-settings` (no bare `os.environ` calls outside config)
- [ ] ✅ `database.py` — async SQLAlchemy engine + `get_db()` dependency injection
- [ ] ✅ `models.py` — ORM models: `Submission` and `Iteration` tables
- [ ] ✅ `schemas.py` — Pydantic v2 request/response models with validation
- [ ] ✅ Five service modules: `docker_service`, `boost_service`, `ai_service`, `patch_service`, `repair_service`
- [ ] ✅ Four router modules: `health`, `repair`, `history`, `evaluate`
- [ ] ✅ Server runs on Uvicorn ASGI server: `uvicorn api.main:app --reload`

### 2.2 API Endpoints
- [ ] ✅ `GET /api/health` — returns status of Docker, AI, DB; used by FE health indicator
- [ ] ✅ `POST /api/repair` — accepts `{code, max_iterations}`, validates, queues background task, returns 202
- [ ] ✅ Code size validated against `MAX_CODE_SIZE_KB` (default 100KB) — returns HTTP 400 if exceeded
- [ ] ✅ `GET /api/repair/{submission_id}/stream` — SSE endpoint, streams JSON events from async generator
- [ ] ✅ `GET /api/repair/{submission_id}` — returns full result with all iteration details
- [ ] ✅ `GET /api/history` — returns 50 most recent submissions without iteration detail
- [ ] ✅ `POST /api/evaluate` — runs batch evaluation from `batch_manifest.yaml`
- [ ] ✅ Swagger / OpenAPI docs available at `/docs` (FastAPI auto-generation)
- [ ] ✅ CORS configured to allow `localhost` frontend origin

### 2.3 Async Architecture
- [ ] ✅ All blocking Docker SDK calls wrapped in `asyncio.run_in_executor()` — event loop never blocked
- [ ] ✅ Repair loop runs as background task (`BackgroundTasks`) — `POST /api/repair` returns immediately
- [ ] ✅ SSE endpoint is a proper async generator consumed by the router
- [ ] ✅ Multiple concurrent repair sessions supported without cross-contamination

---

## 3. Iterative Agentic Repair Loop
*Basis: Sections 3.2.7, 4.4.2, Ravi et al. (2025), Bouzenia et al. (2025), Liventsev et al. (2024)*

### 3.1 Loop Mechanics
- [ ] ✅ Maximum iteration count configurable via ENV (`MAX_ITERATIONS`, default 7)
- [ ] ✅ Loop terminates on success (code executes + Pest passes + mutation score ≥ threshold)
- [ ] ✅ Loop terminates on exhaustion (all iterations used without success)
- [ ] ✅ Each iteration uses a **fresh Docker container** — no state leakage between iterations
- [ ] ✅ Supplementary files (created by `create_file` patches) are re-injected into every new container
- [ ] ✅ Iteration counter tracked and emitted as SSE event on each cycle start
- [ ] ✅ Each iteration's full state saved to `iterations` DB table before loop continues

### 3.2 Seven-Step Sequence (every step must be verifiable in logs)
- [ ] ✅ **Step 1**: `docker_service.create_container()` — fresh container with security limits
- [ ] ✅ **Step 2**: `docker_service.copy_code()` — code written via in-memory tar
- [ ] ✅ **Step 2b**: Supplementary files re-injected via heredoc shell commands
- [ ] ✅ **Step 3**: PHP lint → namespace detection → Tinker validation
- [ ] ✅ **Step 4** (on success): Pest functional test run; if passes → mutation gate
- [ ] ✅ **Step 5** (on failure): `boost_service.query_context()` — schema + docs from inside container
- [ ] ✅ **Step 6**: `ai_service.get_repair()` — LLM called with full enriched context
- [ ] ✅ **Step 7**: `patch_service.apply()` — patch applied; iteration counter increments; loop back to Step 1

### 3.3 Stopping Conditions
- [ ] ✅ Success: code executes clean + Pest passes + mutation score ≥ `MUTATION_SCORE_THRESHOLD`
- [ ] ✅ Exhausted: iteration counter reaches `MAX_ITERATIONS` without success
- [ ] ✅ `create_file` mutation override: if previous patch was `create_file` and mutation score is 0%, accept as success (boilerplate files have no mutations to test)
- [ ] ✅ Final `complete` SSE event emitted with `status: "success"` or `status: "failed"`, final code, iteration count

---

## 4. Laravel Boost Context Module
*Basis: Section 3.2.3, Taylor Otwell (2025a), Chapter 4 Section 4.4.4*

- [ ] ✅ `boost_service.py` runs `php artisan boost:schema --format=text` **inside the container**
- [ ] ✅ `boost_service.py` runs `php artisan boost:docs --query="<error_type>" --limit=3` **inside the container**
- [ ] ✅ Both results combined into a single JSON object injected into repair prompt as `FRAMEWORK_CONTEXT`
- [ ] ✅ In-process cache keyed by `SHA-256(laravel_version + error_text[:500])` — avoids redundant Docker exec on repeated errors
- [ ] ✅ Cache miss correctly executes fresh artisan commands; cache hit skips Docker exec entirely
- [ ] ✅ Boost context (schema + docs) stored in `boost_context` column of `iterations` table
- [ ] ✅ Boost context panel data available via `GET /api/repair/{id}` response
- [ ] ✅ `boost_queried` SSE event emitted when context is retrieved, with `schema: true/false` and `component_type` fields

---

## 5. AI Service Module
*Basis: Section 3.2.3, Xia et al. (2023), Silva et al. (2024), Chapter 4 Section 4.4.3*

### 5.1 Provider Support
- [ ] ✅ Google Gemini (`gemini-2.5-flash`) via OpenAI-compatible endpoint
- [ ] ✅ Groq (`llama-3.3-70b-versatile`) via OpenAI-compatible endpoint
- [ ] ✅ DeepSeek (`deepseek-coder`) via OpenAI-compatible endpoint
- [ ] ✅ OpenAI GPT (`gpt-4o`)
- [ ] ✅ Anthropic Claude (`claude-sonnet-4-6`) via `anthropic` SDK
- [ ] ✅ Ollama (local, `qwen2.5-coder:7b`) via local OpenAI-compatible endpoint
- [ ] ✅ Active provider selected by `DEFAULT_AI_PROVIDER` ENV var at startup
- [ ] ✅ Temperature fixed at `0.0` for all providers — deterministic, reproducible output (thesis evaluation requirement)

### 5.2 Prompt Engineering
*Basis: Xia et al. (2023) — importance of structured prompting*
- [ ] ✅ Repair prompt loaded from `api/prompts/repair_prompt.txt` template file
- [ ] ✅ Template uses `.replace()` substitution — not f-strings (PHP curly braces break f-string parsing)
- [ ] ✅ Prompt includes: (1) runtime error + stack trace, (2) current code, (3) Boost schema, (4) Boost docs excerpts, (5) previous repair attempts summary, (6) explicit JSON-only response instruction
- [ ] ✅ Prompt instructs LLM: return minimal targeted patch (not a full rewrite)
- [ ] ✅ Prompt instructs LLM: generate a deterministic Pest test (no network calls, no time-dependent logic)
- [ ] ✅ Prompt instructs LLM: one of three patch actions only (`replace`, `append`, `create_file`)
- [ ] ✅ Pest test generation prompt stored in `api/prompts/pest_prompt.txt`

### 5.3 Response Parsing and Resilience
- [ ] ✅ AI response parsed as structured JSON with fields: `diagnosis`, `fix_description`, `patch` (action, target, replacement, filename), `pest_test`
- [ ] ✅ PHP namespace backslash repair: `App\Models\Product` → `App\\Models\\Product` before `json.loads()`
- [ ] ✅ Markdown fence stripping: backtick code fences removed before JSON parse
- [ ] ✅ `tenacity` retry decorator: up to 3 retries with exponential backoff on `ValueError` / `JSONDecodeError`
- [ ] ✅ Full AI prompt stored in `ai_prompt` column of `iterations` table
- [ ] ✅ Raw AI response stored in `ai_response` column of `iterations` table

---

## 6. Patch Service Module
*Basis: Section 3.2.7, Chapter 4 Section 4.4.5*

- [ ] ✅ `replace` action: single-occurrence `str.replace(target, replacement, 1)` on current code
- [ ] ✅ `append` action: concatenates `"\n\n" + replacement` to end of current code
- [ ] ✅ `create_file` action: signals `repair_service` to write new file at `patch.filename` inside container
- [ ] ✅ `PatchApplicationError` raised if `replace` target string not found in current code
- [ ] ✅ `strip_markdown_fences()` applied to all AI replacement code before patching
- [ ] ✅ Patch action type, target, and replacement stored in `patch_applied` column of `iterations` table
- [ ] ✅ New files created by `create_file` added to `supplementary_files` dict in repair service for re-injection in subsequent iterations

---

## 7. Pest Testing and Mutation Gate
*Basis: Tian et al. (2024), Ravi et al. (2025), Section 3.2.3, Section 4.4.1*

- [ ] ✅ Pest functional test (`pest --filter=RepairTest`) executed inside container after every successful code execution
- [ ] ✅ Pest test code generated by AI included in the repair prompt response as `pest_test` field
- [ ] ✅ AI-generated Pest test written into container before test run
- [ ] ✅ Pest test code stored in `pest_test_code` column of `iterations` table
- [ ] ✅ Pest test output stored in `pest_test_result` column of `iterations` table
- [ ] ✅ `pest_result` SSE event emitted with `status: "pass"/"fail"` and `output` fields
- [ ] ✅ Mutation gate: `./vendor/bin/pest --mutate --coverage-pcov` run after Pest functional test passes
- [ ] ✅ Mutation score parsed from Pest output by `_parse_mutation_score()` function
- [ ] ✅ Mutation score threshold configurable via `MUTATION_SCORE_THRESHOLD` ENV var (default: 80%)
- [ ] ✅ `mutation_result` SSE event emitted with `score`, `threshold`, `passed` fields
- [ ] ✅ Mutation score stored in `mutation_score` column of `iterations` table
- [ ] ✅ `create_file` mutation override: 0% accepted as success when previous action was `create_file`

---

## 8. Data Persistence (SQLite)
*Basis: Section 3.2.4, Park & Choi (2018)*

### 8.1 Submissions Table
- [ ] ✅ `id` — UUID primary key
- [ ] ✅ `created_at` — UTC datetime of submission
- [ ] ✅ `original_code` — raw submitted PHP code
- [ ] ✅ `status` — state machine: `pending` → `running` → `success` / `failed`
- [ ] ✅ `total_iterations` — count of iterations that ran
- [ ] ✅ `final_code` — repaired code (null if status = failed)
- [ ] ✅ `error_summary` — human-readable failure reason (null if success)

### 8.2 Iterations Table
- [ ] ✅ `id` — UUID primary key
- [ ] ✅ `submission_id` — FK to submissions
- [ ] ✅ `iteration_num` — 0-indexed integer
- [ ] ✅ `code_input` — code version at start of this iteration
- [ ] ✅ `execution_output` — container stdout
- [ ] ✅ `error_logs` — combined stderr + stdout from failed exec
- [ ] ✅ `boost_context` — JSON string from boost_service
- [ ] ✅ `ai_prompt` — full prompt sent to LLM
- [ ] ✅ `ai_response` — raw LLM response JSON
- [ ] ✅ `patch_applied` — string representation of PatchSpec
- [ ] ✅ `pest_test_code` — Pest test generated by AI
- [ ] ✅ `pest_test_result` — Pest output
- [ ] ✅ `mutation_score` — float percentage from pest --mutate
- [ ] ✅ `status` — `failed` or `success`
- [ ] ✅ `duration_ms` — wall-clock duration of iteration in milliseconds
- [ ] ✅ `created_at` — UTC datetime

### 8.3 Database Behaviour
- [ ] ✅ Database file auto-created at `data/repair.db` on first startup (no manual migration needed)
- [ ] ✅ ACID compliance — no corrupted records even if application crashes mid-iteration (Park & Choi, 2018)
- [ ] ✅ Deleting `data/repair.db` and restarting fully recreates all tables

---

## 9. MCP Server
*Basis: Section 3.2.6, Taylor Otwell (2025b), Section 4.4.7*

- [ ] ✅ `mcp/server.py` implements JSON-RPC 2.0 over stdio transport (MCP standard)
- [ ] ✅ Responds to `tools/list` requests with descriptor for `repairLaravelApiCode` tool
- [ ] ✅ `repairLaravelApiCode` accepts: `code` (string, required), `max_iterations` (int, optional, 1–10)
- [ ] ✅ On `tools/call`: submits code to FastAPI backend via HTTP POST
- [ ] ✅ Polls `GET /api/repair/{id}` every 1.5 seconds until complete or 10-minute timeout
- [ ] ✅ Returns structured result: `status`, `submission_id`, `iterations`, `repaired_code`, `diagnosis`, `mutation_score`
- [ ] ✅ Cursor integration config documented in `.cursor/mcp.json` example
- [ ] ✅ `REPAIR_API_URL` ENV var configures which FastAPI instance the MCP server calls

---

## 10. Evaluation Framework
*Basis: Section 4.5, batch_manifest.yaml, Chapter Five contribution claims*

- [ ] ✅ `batch_manifest.yaml` defines: AI provider, model, temperature, max_iterations, mutation threshold, batch_size, resource limits
- [ ] ✅ Three error type cases defined: `missing_model`, `wrong_namespace`, `missing_import`
- [ ] ✅ `POST /api/evaluate` endpoint triggers full batch run
- [ ] ✅ Results written to `tests/integration/results/batch_report.csv`
- [ ] ✅ Ablation flag `use_boost_context: true/false` — disabling measures Boost's contribution to success rate
- [ ] ✅ Ablation flag `use_mutation_gate: true/false` — disabling measures gate's contribution
- [ ] ✅ Temperature locked at `0.0` across all evaluation runs — deterministic, reproducible (thesis claim)
- [ ] ✅ Each case in `tests/fixtures/` has a corresponding broken PHP file that triggers the target error type
- [ ] ✅ `missing_model.php` — references `App\Models\Product` which does not exist
- [ ] ✅ `wrong_namespace.php` — controller namespace does not match file path
- [ ] ✅ `missing_import.php` — uses `Str::` facade without `use Illuminate\Support\Str;`

---

## 11. Unit and Integration Tests
*Basis: Chapter 4 Section 4.4, pytest configuration*

- [ ] ✅ `tests/conftest.py` — shared fixtures with mocked Docker containers and sample PHP code
- [ ] ✅ `test_ai_service.py` — JSON parsing, prompt building, PHP namespace backslash repair, markdown fence stripping
- [ ] ✅ `test_boost_service.py` — context fetching, cache hit/miss behaviour, component type detection
- [ ] ✅ `test_patch_service.py` — all three patch actions (`replace`, `append`, `create_file`), `PatchApplicationError` on missing target
- [ ] ✅ `test_repair_service.py` — success path, exhausted iterations, mutation score below threshold, `create_file` mutation override
- [ ] ✅ All unit tests mock Docker layer — pass without Docker running or API keys set
- [ ] ✅ `pytest.ini` sets `asyncio_mode = auto` — no `@pytest.mark.asyncio` decorators needed
- [ ] ✅ Integration tests tagged `@pytest.mark.integration` — excluded from default run
- [ ] ✅ `tests/integration/test_full_repair.py` — end-to-end test requiring Docker + real API key

---

## 12. Configuration and Security
*Basis: Section 4.2.1, MANUAL.md Section 6*

- [ ] ✅ All secrets in `.env` — never hardcoded in source files
- [ ] ✅ `.env` in `.gitignore` — only `.env.example` committed
- [ ] ✅ `config.py` is the single point of environment variable access
- [ ] ✅ `SECRET_KEY` ENV var defined (even if JWT not yet enforced in prototype)
- [ ] ✅ `DEBUG=false` in production ENV
- [ ] ✅ AI API keys for all six providers documented in `.env.example`
- [ ] ✅ `MUTATION_SCORE_THRESHOLD`, `MAX_ITERATIONS`, `MAX_CODE_SIZE_KB` all configurable via ENV

---

## 13. Developer Scripts and Utilities
*Basis: MANUAL.md Section 5 and 17*

- [ ] ✅ `start.sh` — one-command setup: creates venv, installs deps, copies .env.example, builds Docker image, runs unit tests, starts server
- [ ] ✅ `scripts/dump_last_log.py` — prints last iteration logs from DB for debugging
- [ ] ✅ `scripts/run_case.sh` — runs a single evaluation case from batch manifest
- [ ] ✅ `requirements.txt` — all Python dependencies pinned with versions
- [ ] ✅ Health check: `GET /api/health` returns `{"status":"ok","docker":"connected","ai":"key_set","db":"connected"}`
- [ ] ✅ `docker run --rm laravel-sandbox:latest php -v` — verifies PHP 8.3 in image
- [ ] ✅ `docker run --rm laravel-sandbox:latest php artisan --version` — verifies Laravel 12
- [ ] ✅ `docker run --rm laravel-sandbox:latest ./vendor/bin/pest --version` — verifies Pest 3

---

## 14. Thesis-Specific Requirements
*These items must exist because the thesis explicitly claims them — missing any undermines the academic argument*

- [ ] ✅ **Execution-first validation** — code is actually run in Docker, not just statically analysed (Chapter 1.2 gap claim)
- [ ] ✅ **Boost inside the container** — Boost runs within the same container as the code, not as a separate service (Chapter 3.2.1 claim)
- [ ] ✅ **Pest test generation** — every repair produces a Pest test, not just error elimination (Chapter 3.2.3 claim)
- [ ] ✅ **Mutation gate** — 80% mutation coverage threshold enforced, not just test pass/fail (Chapter 3.2.3 claim)
- [ ] ✅ **Agentic loop** — the system plans, executes, observes, and self-corrects across multiple steps (Chapter 1.6 definition of Agentic AI)
- [ ] ✅ **MCP server stub** — even as a prototype, the MCP endpoint must exist and be callable (Chapter 3.2.6, 4.4.7)
- [ ] ✅ **SQLite empirical log** — every repair fully logged for dataset analysis (Chapter 4.5 contribution claim)
- [ ] ✅ **Six AI providers** — multi-provider support implemented, not just one (Chapter 3.2.3, Chapter 4.2.3)
- [ ] ✅ **Ablation study support** — `use_boost_context` and `use_mutation_gate` flags functional in batch evaluator (Chapter 5.2 contribution claim)
- [ ] ✅ **Reproducible evaluation** — temperature = 0.0 enforced for all thesis evaluation runs (Chapter 5.2 methodology claim)

---

## 🔶 Nice to Have (Further Work / Bonus)

- [ ] 🔶 JWT authentication on API endpoints (Chapter 1.5 scope note)
- [ ] 🔶 Rate limiting per client on FastAPI (MCP production readiness)
- [ ] 🔶 Persistent container pool — pre-warmed containers waiting rather than cold-starting per request
- [ ] 🔶 PostgreSQL migration path documented (Chapter 5.3 recommendation)
- [ ] 🔶 Fine-tuned repair model using accumulated SQLite dataset (Chapter 5.3 recommendation)
- [ ] 🔶 GitHub Actions CI/CD integration config (Chapter 5.3 recommendation)
- [ ] 🔶 Broader error type coverage: misconfigured Eloquent relationships, broken Sanctum chains, N+1 queries (Chapter 5.3)
- [ ] 🔶 Webhook adapter for GitLab/GitHub PR integration (Chapter 5.3)
- [ ] 🔶 Automatic prompt self-improvement from repair history (Chapter 5.3)
- [ ] 🔶 Multi-framework extension: Symfony, Express (Chapter 5.3)
- [ ] 🔶 Biometric / liveness detection for code authorship (not in scope but mentioned as inspiration from Tanimowo peer thesis)
- [ ] 🔶 `dump_last_log.py` extended to HTML report for easier debugging

---

*Every ✅ item is directly traceable to a thesis section, a cited work, or a system design commitment made in Chapters 1–5. Removing any ✅ item creates a gap between what the thesis claims and what the system does.*
