# Laravel AI Repair Platform — Backend Implementation Checklist
**Source authority:** MANUAL.md · BACKEND_SPEC.md · walkthrough.md · Actual codebase (2026-04-22)**
**Version:** 2.0 | Adamu Joseph Obinna

> Legend: ✅ Must Have (thesis-critical) · 🔶 Nice to Have · ❌ Confirmed Missing/Broken · ⚠️ Partially Done
> Every ✅ item maps to at least one thesis claim. Items marked ❌ or ⚠️ are honest gaps.

---

## 1. Docker Sandbox Environment
*Basis: Section 3.2.1, Chapter 4*

### 1.1 Image Contents
- [x] ✅ Base image is `php:8.3-cli-alpine`
- [x] ✅ Composer 2.x installed and on PATH
- [x] ✅ Laravel 12.x installed via `composer create-project laravel/laravel sandbox "12.*"`
- [x] ✅ Laravel Boost installed as dev dependency
- [x] ✅ `php artisan boost:install` executed during image build
- [x] ✅ Pest 3.x installed: `pestphp/pest` + `pestphp/pest-plugin-laravel`
- [x] ✅ Pest Mutate plugin installed: `pestphp/pest-plugin-mutate`
- [x] ✅ `pcov` PHP extension installed (required for mutation coverage)
- [x] ✅ `php.ini` configured with `memory_limit`, `max_execution_time`
- [x] ✅ Image builds successfully

### 1.2 Runtime Security Constraints
- [x] ✅ `--network=none` — zero internet access
- [x] ✅ `--memory=512m` — memory cap enforced
- [x] ✅ `--pids-limit=64` — fork bomb prevention
- [x] ✅ `--security-opt=no-new-privileges:true`
- [x] ✅ `--nano-cpus` CPU limited to 0.5 cores
- [x] ✅ Every container destroyed in `finally` block — zero leaks
- [x] ✅ User code injected via in-memory tar archive — no host temp files

### 1.3 Code Injection and Execution
- [x] ✅ Submitted PHP written to `/submitted/code.php`
- [x] ✅ PHP namespace and class name detected via PHP one-liners (not just grep)
- [x] ✅ File copied to correct Laravel PSR-4 path matching namespace (`sandbox_service.place_code_in_laravel`)
- [x] ✅ `composer dump-autoload` run after injection
- [x] ✅ PHP lint: `php -l /submitted/code.php` — first gate
- [x] ✅ Laravel Tinker validation — `CLASS_OK` sentinel parsed from output
- [x] ✅ `has_php_fatal` property on `ExecResult` handles PHP fatals with zero exit code
- [x] ✅ `ExecResult` dataclass: `stdout`, `stderr`, `exit_code`, `duration_ms`
- [x] ✅ SQLite configured automatically (`sandbox_service.setup_sqlite`) — needed because `--network=none` blocks MySQL
- [x] ✅ Route auto-scaffolded BEFORE Boost query (`scaffold_route` → `boost_service.query_context`)
- [x] ✅ CRLF and UTF-8 BOM stripped from submitted code (`_normalize_code`)
- [x] ✅ Named-class migrations normalised to anonymous syntax (`_normalize_migration`)

---

## 2. FastAPI Coordinator Service
*Basis: Section 3.2.2*

### 2.1 Application Structure
- [x] ✅ `main.py` — app entry point, lifespan hooks, CORS, rate limiting, router registration
- [x] ✅ `config.py` — all settings from `.env` via `pydantic-settings`
- [x] ✅ `database.py` — async SQLAlchemy engine + `get_db()` dependency
- [x] ✅ `models.py` — ORM: `Submission`, `Iteration`, `RepairSummary` tables
- [x] ✅ `schemas.py` — Pydantic v2 request/response models
- [x] ✅ `logging_config.py` — unified console + rotating file handler (10 MB × 5 backups), `submission_id` context field
- [x] ✅ 11 service modules: `docker_service`, `sandbox_service`, `boost_service`, `ai_service`, `patch_service`, `repair_service`, `escalation_service`, `context_service`, `evaluation_service`, `auth_service`, `limiter`
- [x] ✅ 6 router modules: `health`, `repair`, `history`, `evaluate`, `stats`, `admin`
- [x] ✅ Server runs on Uvicorn ASGI

### 2.2 API Endpoints
- [x] ✅ `GET /api/health`
- [x] ✅ `POST /api/repair` — accepts `{code, max_iterations, use_boost, use_mutation_gate, prompt}`
- [x] ✅ `GET /api/repair/{id}/stream` — SSE endpoint
- [x] ✅ `GET /api/repair/{id}` — full result with all iteration details
- [x] ✅ `GET /api/history`
- [x] ✅ `POST /api/evaluate` — batch evaluation
- [x] ✅ `GET /api/stats` — aggregate statistics
- [x] ✅ `DELETE /api/admin/submissions/{id}` — admin hard-delete
- [x] ✅ Swagger / OpenAPI docs at `/docs`

### 2.3 Async Architecture
- [x] ✅ All blocking Docker SDK calls in `asyncio.run_in_executor()` — event loop never blocked
- [x] ✅ Repair loop runs as `BackgroundTask` — `POST /api/repair` returns 202 immediately
- [x] ✅ SSE endpoint is a proper async generator consumed by the router
- [x] ✅ Rate limiting via `slowapi` with `RateLimitExceeded` handler

---

## 3. Iterative Agentic Repair Loop
*Basis: Sections 3.2.7, 4.4.2*

### 3.1 Loop Mechanics
- [x] ✅ `MAX_ITERATIONS` default = 4 (configurable via ENV)
- [x] ✅ Loop terminates on success (exec OK + Pest pass + mutation ≥ threshold)
- [x] ✅ Loop terminates on exhaustion
- [x] ✅ **Single persistent container** per submission (V2 model — not fresh per iteration)
- [x] ✅ Iteration counter tracked and emitted as `iteration_start` SSE event
- [x] ✅ Each iteration saved to DB before loop continues
- [x] ✅ `ai_model_used` persisted per iteration (critical for research data)
- [x] ✅ Partial `mutation_score` stored even on failed iterations

### 3.2 13-Step Sequence Per Iteration
- [x] ✅ **Step 1**: `copy_code()` — code written via tar stream
- [x] ✅ **Step 2**: `php -l` lint gate
- [x] ✅ **Step 3**: `detect_class_info()` — namespace + classname + FQCN
- [x] ✅ **Step 4**: `place_code_in_laravel()` — PSR-4 placement + Tinker validation
- [x] ✅ **Step 5**: `scaffold_route()` — BEFORE boost so route:list sees the route
- [x] ✅ **Step 6**: `boost_service.query_context()` — schema + docs from inside container
- [x] ✅ **Step 7**: `context_service.retrieve_similar_repairs()` — sliding window memory
- [x] ✅ **Step 8**: `escalation_service.build_escalation_context()` — stuck loop detection
- [x] ✅ **Step 9**: `ai_service.get_repair()` — LLM call with full context
- [x] ✅ **Step 10**: `ensure_covers_directive()` — injects `covers()` if missing
- [x] ✅ **Step 11**: `patch_service.apply_all()` — applies patches, handles forbidden files
- [x] ✅ **Step 12**: `run_pest_test()` — baseline HTTP gate
- [x] ✅ **Step 13**: `run_mutation_test()` — mutation gate (if AI test present)

### 3.3 Stopping Conditions
- [x] ✅ Success: exec OK + Pest pass + mutation ≥ `MUTATION_SCORE_THRESHOLD`
- [x] ✅ Baseline-only success: exec OK + Pest pass + no AI test yet (mutation skipped)
- [x] ✅ `create_file` mutation override: 0% accepted as success when prev action = `create_file`
- [x] ✅ Exhausted: reaches `MAX_ITERATIONS` without success
- [x] ✅ AI failure: `AIServiceError` after all fallbacks exhausted → immediate fail

---

## 4. Laravel Boost Context Module
*Basis: Section 3.2.3, Chapter 4 Section 4.4.4*

- [x] ✅ `boost:schema --format=json` inside container → fallback to `db:show --json`
- [x] ✅ `boost:docs --query=<component_type>` inside container
- [x] ✅ `route:list --json` always fetched as supplementary context
- [x] ✅ `routes/api.php` raw content appended to docs excerpts
- [x] ✅ Cache keyed by `SHA-256(submission_id + framework_version + component_type)` — NOT raw error text
- [x] ✅ Cross-submission cache contamination prevented (scoped by `submission_id`)
- [x] ✅ Score-based component type detection (not `if/elif`) across 6 types
- [x] ✅ Noise filtering: strips default Laravel tables and internal Boost/Sanctum routes
- [x] ✅ Fallback: lists model files if no schema available
- [x] ✅ `boost_queried` SSE event emitted with `schema` and `component_type` fields
- [x] ✅ Boost context stored in `boost_context` column of `iterations` table

---

## 5. AI Service Module
*Basis: Section 3.2.3, Chapter 4 Section 4.4.3*

### 5.1 Provider Support
- [x] ✅ Nvidia NIM (`Qwen/Qwen2.5-Coder-32B-Instruct`, `meta/llama-3.3-70b-instruct`)
- [x] ✅ Dashscope / Alibaba (`deepseek-v3`, `qwen-max`)
- [x] ✅ Groq (`llama-3.3-70b-versatile`)
- [x] ✅ Cerebras (`llama-3.3-70b`)
- [x] ✅ Gemini (`gemini-2.0-flash`, `gemini-2.5-flash`)
- [x] ✅ DeepSeek (`deepseek-coder`) via OpenAI-compatible endpoint
- [x] ✅ OpenAI (`gpt-4o`)
- [x] ✅ Anthropic Claude via `anthropic` SDK
- [x] ✅ Ollama (local, `qwen2.5-coder:7b`)
- [x] ✅ `ROTATION_CHAIN` (4 models) for batch evaluation — rotates per iteration
- [x] ✅ `FALLBACK_CHAIN` (8 entries) for single submissions
- [x] ✅ `ai_model_used` (`provider/model`) recorded per iteration in DB
- [x] ✅ Temperature fixed at `0.0` — deterministic, reproducible

### 5.2 Prompt Engineering
- [x] ✅ Repair prompt loaded from `api/prompts/repair_prompt.md` template
- [x] ✅ `.replace()` substitution — not f-strings (PHP curly braces would break parsing)
- [x] ✅ 7 template fields: `{code}`, `{error}`, `{boost_context}`, `{escalation_context}`, `{user_prompt}`, `{previous_attempts}`, `{similar_past_repairs}`
- [x] ✅ User prompt elevated in hierarchy (above default instructions)
- [x] ✅ Spatie PHP coding standards embedded in system prompt
- [x] ✅ Prompt instructs LLM: respond with `full_replace` or `create_file` only (replace/append banned)
- [x] ✅ Prompt instructs LLM: generate Pest test with `covers()` directive

### 5.3 Response Parsing and Resilience
- [x] ✅ `<think>...</think>` blocks stripped (DeepSeek R1 chain-of-thought)
- [x] ✅ Brace-depth JSON extraction — handles prose before/after and markdown fences
- [x] ✅ `_fix_json_escapes()` — repairs PHP namespace backslashes before `json.loads()`
- [x] ✅ `patches` array parsed (multi-patch architecture)
- [x] ✅ Legacy single `patch` key supported for backward compatibility
- [x] ✅ AI wrapping patches as dict instead of list — normalised
- [x] ✅ `filename or target or path` key unification across different LLM interpretations
- [x] ✅ `tenacity` retry: 3× on `ValueError`/`JSONDecodeError`; 3× on network/rate-limit errors
- [x] ✅ JSON mode (`response_format={"type":"json_object"}`) for providers that support it
- [x] ✅ Full AI prompt stored in `ai_prompt` column
- [x] ✅ Raw AI response stored in `ai_response` column

---

## 6. Patch Service Module
*Basis: Section 3.2.7, Chapter 4 Section 4.4.5*

- [x] ✅ `full_replace` action: replaces entire file content
- [x] ✅ `create_file` action: signals loop to write a new file
- [x] ✅ `replace` and `append` actions: **banned** — raise `PatchApplicationError` immediately
- [x] ✅ Forbidden file blocklist: `routes/api.php`, `routes/web.php`, `routes/console.php`, `routes/channels.php`
- [x] ✅ Blocked files logged via `log_line` SSE event — not raised as exception
- [x] ✅ `strip_markdown_fences()` applied to all AI replacement content
- [x] ✅ `apply_all()` returns `ApplyAllResult` with `updated_code`, `created_files`, `actions_taken`, `skipped_forbidden`
- [x] ✅ Created files written to container and flushed via `composer dump-autoload` + `php artisan migrate`
- [x] ✅ Migration content normalised to anonymous class syntax before writing

---

## 7. Pest Testing and Mutation Gate
*Basis: Tian et al. (2024), Section 3.2.3*

- [x] ✅ System-controlled baseline Pest test generated (`generate_baseline_pest_test`) — HTTP assertion, no AI involvement
- [x] ✅ AI-generated Pest test used for mutation gate only
- [x] ✅ AI test linted (`php -l`) before mutation gate — syntax errors caught early
- [x] ✅ `ensure_covers_directive()` injects `covers()` and `use function Pest\Laravel\{...};` if missing
- [x] ✅ Mutation gate skipped if no AI test present — baseline pass accepted
- [x] ✅ Pest run: `./vendor/bin/pest --filter=RepairTest --no-coverage`
- [x] ✅ Mutation run: `./vendor/bin/pest --mutate` (120 s timeout)
- [x] ✅ Mutation output classified: `covers_missing` → score=0 fail; `dependency_failure` → score=0 fail; `infra_failure` → soft-pass
- [x] ✅ Score parsed by 6-pattern regex with ANSI stripping
- [x] ✅ Threshold configurable via `MUTATION_SCORE_THRESHOLD` ENV var (default 80%)
- [x] ✅ `mutation_result` SSE event: `score`, `threshold`, `passed`, `output`, `duration_ms`
- [x] ✅ `mutation_score` stored on every iteration (partial score on fails too)
- [x] ✅ Laravel application log captured on Pest failure (`capture_laravel_log` — last 40 lines)
- [x] ✅ `TEST_DEPENDENCY_ERROR` prefix injected when crash markers detected in Pest output
- ⚠️ Mutation score parser returns silent `0.0` with no SSE event when no regex pattern matches

---

## 8. Escalation Service
*Basis: Section 3.2.7*

- [x] ✅ 4-rule stuck-loop detection evaluated after every failed iteration
- [x] ✅ Rule 1: Repeated diagnoses (fuzzy match ≥ 70% word overlap, threshold = 2 identical)
- [x] ✅ Rule 2: Consecutive patch failures → forces `full_replace`
- [x] ✅ Rule 3: `create_file` without fixing original file → demands `full_replace` of original
- [x] ✅ Rule 4: Dependency Guard — detects duplicate `create_file` paths across iterations
- [x] ✅ Escalation context injected into next AI prompt as `{escalation_context}`
- [x] ✅ `log_line` SSE event emitted when escalation triggers

---

## 9. Context Service (Sliding Window Memory)
*Basis: Section 3.2.7 — agentic self-correction*

- [x] ✅ 200-item `deque` sliding window (auto-prunes at maxlen)
- [x] ✅ Cold-start: populated from DB on first call (`_ensure_cache_loaded`)
- [x] ✅ Retrieval score: `(similarity × 0.7) + (efficiency × 0.3)`
- [x] ✅ Similarity via `SequenceMatcher` character-level ratio
- [x] ✅ Threshold: 0.6 minimum similarity to surface a match
- [x] ✅ Top-3 matches injected as `{similar_past_repairs}` in AI prompt
- [x] ✅ Error signature extraction: 4-level priority (Laravel log → Exception → Fatal → first line)
- [x] ✅ `RepairSummary` table: stores `error_type`, `diagnosis`, `fix_applied`, `what_did_not_work`, `iterations_needed`
- [x] ✅ Successful repairs stored immediately and added to in-memory cache

---

## 10. Data Persistence (SQLite)
*Basis: Section 3.2.4*

### 10.1 Submissions Table
- [x] ✅ `id` — UUID PK
- [x] ✅ `user_id`, `user_prompt` — optional multi-user fields
- [x] ✅ `created_at` — UTC datetime
- [x] ✅ `original_code`, `final_code`, `error_summary`
- [x] ✅ `status` — `pending → running → success / failed`
- [x] ✅ `total_iterations`
- [x] ✅ `case_id`, `category`, `experiment_id` — batch evaluation metadata

### 10.2 Iterations Table
- [x] ✅ `id`, `submission_id` (FK), `iteration_num`
- [x] ✅ `code_input`, `execution_output`, `error_logs`
- [x] ✅ `boost_context` (JSON)
- [x] ✅ `ai_prompt`, `ai_response`
- [x] ✅ `ai_model_used` — e.g. `"nvidia/Qwen/Qwen2.5-Coder-32B-Instruct"`
- [x] ✅ `patch_applied` — stringified list of `PatchSpec` objects
- [x] ✅ `pest_test_code`, `pest_test_result`
- [x] ✅ `mutation_score` (Float, nullable — NULL if gate not reached)
- [x] ✅ `status`, `duration_ms`, `created_at`

### 10.3 RepairSummary Table
- [x] ✅ `error_type`, `diagnosis`, `fix_applied`, `what_did_not_work`, `iterations_needed`
- [x] ✅ Populated only on success; feeds sliding window memory

### 10.4 Database Behaviour
- [x] ✅ Auto-created at `data/repair.db` on startup via lifespan hook
- [x] ✅ Delete DB + restart = full table recreation

---

## 11. MCP Server
*Basis: Section 3.2.6, Section 4.4.7*

- [x] ✅ `mcp/server.py` — JSON-RPC 2.0 over stdio transport
- [x] ✅ `tools/list` → describes `repairLaravelApiCode` tool
- [x] ✅ `tools/call` → submits to FastAPI, polls until complete
- [x] ✅ Returns `status`, `submission_id`, `iterations`, `repaired_code`, `diagnosis`, `mutation_score`
- [x] ✅ `REPAIR_API_URL` ENV var configures target FastAPI instance

---

## 12. Evaluation Framework
*Basis: Section 4.5*

- [x] ✅ `batch_manifest.yaml` defines provider, model, temperature, max_iterations, mutation threshold
- [x] ✅ `batch_manifest_boost_off.yaml` — ablation variant with `use_boost_context: false`
- [x] ✅ `POST /api/evaluate` triggers full batch run
- [x] ✅ Results written to `data/results/` as CSV
- [x] ✅ `use_boost_context` flag — measures Boost's contribution
- [x] ✅ `use_mutation_gate` flag — measures gate's contribution
- [x] ✅ Temperature locked at `0.0` — deterministic, reproducible
- [x] ✅ `scratch_analyze.py` — post-run analysis script
- ⚠️ Batch evaluation is sequential only — no parallelism (Docker + SQLite constraint)

---

## 13. Logging
*Basis: MANUAL.md Section 17*

- [x] ✅ Unified logging: console + `data/logs/repair_platform.log`
- [x] ✅ Rotating file handler: 10 MB per file, 5 backups, UTF-8
- [x] ✅ Always DEBUG to file; INFO to console (DEBUG in debug mode)
- [x] ✅ `submission_id` field in log format string via `ContextFormatter`
- [x] ✅ `LoggerAdapter` used in `repair_service.py` with `{"submission_id": id}`
- [x] ✅ Noisy 3rd-party loggers silenced (`docker`, `urllib3`, `asyncio` → WARNING)
- [x] ✅ Uvicorn logs redirected through root logger (`propagate=True`)
- [x] ✅ **`submission_id` shows `"Global"` in ~90% of log lines** — fixed via `ContextVar`-based logging `Filter` and thread `ctx_log`.

---

## 14. Unit and Integration Tests
*Basis: Chapter 4 Section 4.4*

- [x] ✅ `tests/conftest.py` — shared fixtures with mocked Docker
- [x] ✅ `test_ai_service.py` — JSON parsing, prompt building, escape repair, `<think>` stripping
- [x] ✅ `test_boost_service.py` — context fetching, cache, component detection
- [x] ✅ `test_patch_service.py` — `full_replace`, `create_file`, forbidden file blocking, `PatchApplicationError`
- [x] ✅ `test_repair_service.py` — success path, exhausted iterations, mutation override
- [x] ✅ All unit tests mock Docker — pass without Docker or API keys
- [x] ✅ `pytest.ini`: `asyncio_mode = auto`
- [x] ✅ Integration tests tagged `@pytest.mark.integration`

---

## 15. Configuration and Security
*Basis: Section 4.2.1*

- [x] ✅ All secrets in `.env` — never hardcoded
- [x] ✅ `.env` in `.gitignore` — only `.env.example` committed
- [x] ✅ `config.py` is single point of ENV access
- [x] ✅ `REPAIR_TOKEN` auth header on protected endpoints
- [x] ✅ `DEBUG=false` in production ENV
- [x] ✅ `MUTATION_SCORE_THRESHOLD`, `MAX_ITERATIONS`, `MAX_CODE_SIZE_KB` configurable via ENV
- ⚠️ Mutation test timeout (120 s) is hardcoded in `sandbox_service.py` — not exposed via ENV

---

## 16. Developer Scripts and Utilities
*Basis: MANUAL.md Section 5 and 17*

- [x] ✅ `start.sh` — venv, deps, .env copy, Docker build, server start
- [x] ✅ `scripts/run_batch_eval.sh` — trigger batch evaluation
- [x] ✅ `scripts/run_single_case.sh` — run one case
- [x] ✅ `scripts/smoke_test_api.sh` — curl-based API smoke test
- [x] ✅ `scripts/test_llms.py` — provider connectivity tester
- [x] ✅ `scratch_test_case.py` — run single repair via Python
- [x] ✅ `scratch_analyze.py` — post-batch result analysis
- [x] ✅ `requirements.txt` — all Python dependencies
- [x] ✅ `GET /api/health` — Docker, AI, DB connectivity status

---

## 17. Thesis-Specific Requirements
*These must exist because the thesis explicitly claims them*

- [x] ✅ **Execution-first validation** — code actually run in Docker, not just statically analysed
- [x] ✅ **Boost inside container** — Boost runs within the sandbox, not as external service
- [x] ✅ **Baseline + AI Pest test** — system generates baseline; AI generates mutation-targeted test
- [x] ✅ **Mutation gate** — 80% threshold enforced with real `pest --mutate`
- [x] ✅ **Agentic loop** — plans, executes, observes, self-corrects (escalation + memory)
- [x] ✅ **MCP server** — callable prototype exists
- [x] ✅ **SQLite empirical log** — every iteration fully persisted for dataset analysis
- [x] ✅ **Multi-model rotation** — 4-model `ROTATION_CHAIN` for batch; 8-entry `FALLBACK_CHAIN` for single
- [x] ✅ **`ai_model_used` per iteration** — enables per-model performance analysis
- [x] ✅ **Ablation support** — `use_boost_context` and `use_mutation_gate` flags functional
- [x] ✅ **Reproducible evaluation** — temperature = 0.0 enforced
- [x] ✅ **Sliding window memory** — 200-item RL-weighted repair history injected into prompts

---



*Every ✅ item is directly traceable to a thesis section, cited work, or system design commitment. Items marked ⚠️ or ❌ are honest engineering gaps that do not invalidate the core thesis claims but must be acknowledged.*
