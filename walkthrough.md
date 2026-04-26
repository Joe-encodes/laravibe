# LaraVibe AI Repair Engine — Project Walkthrough

**Last updated:** 2026-04-22  
**Conversation series:** dc5d3914 → 91a2f97a → cae39008 → f28ee76f → f46d7b07 → 44ea3b32 → b1da13d1

---

## 1. What Was Built

An end-to-end **automated PHP/Laravel API repair platform** for academic research. The system:

1. Accepts broken PHP/Laravel REST API code via a FastAPI backend.
2. Spins up an isolated Docker container per submission.
3. Feeds the runtime error to a large language model.
4. Applies the AI's patch using a strict `full_replace` / `create_file` architecture.
5. Re-runs **Pest** tests and a **mutation gate** to validate correctness.
6. Repeats up to `MAX_ITERATIONS=4` or until the code is healthy.
7. Persists every iteration (code, error, boost context, AI prompt, AI response, model used, mutation score, duration) to SQLite and CSV for research data analysis.

---

## 2. Full Architecture

```
Broken PHP ──► FastAPI (api/main.py)
                    │
                    ├── POST /api/repair       ← single-case endpoint
                    └── POST /api/evaluate     ← batch endpoint
                              │
                    ┌─────────▼──────────────────────────────┐
                    │          repair_service.py              │
                    │  (Async generator — yields SSE events)  │
                    │                                         │
                    │  Per iteration:                         │
                    │   1. copy_code → container              │
                    │   2. php -l lint gate                   │
                    │   3. detect_class_info()                │
                    │   4. place_code_in_laravel()            │
                    │   5. scaffold_route()  ← BEFORE boost   │
                    │   6. boost_service.query_context()      │
                    │   7. context_service.retrieve_similar() │
                    │   8. escalation_service.build_context() │
                    │   9. ai_service.get_repair()            │
                    │  10. sandbox_service.ensure_covers()    │
                    │  11. patch_service.apply_all()          │
                    │  12. run_pest_test()                    │
                    │  13. run_mutation_test() (if AI test)   │
                    │  14. _save_iteration() → SQLite + CSV   │
                    └─────────────────────────────────────────┘
                              │
                    SQLite DB (data/repair.db)
                    CSV (data/results/)
                    Log file (data/logs/repair_platform.log)
```

---

## 3. Services — What Each File Does

| File | Responsibility |
|---|---|
| `api/main.py` | FastAPI app init, middleware (CORS, rate limiting), router registration, unified logging setup |
| `api/logging_config.py` | Sets up console + rotating file handler (10 MB × 5 backups) with `submission_id` context |
| `api/models.py` | SQLAlchemy ORM: `Submission`, `Iteration`, `RepairSummary` |
| `api/services/repair_service.py` | Main async generator loop — orchestrates all services per iteration |
| `api/services/ai_service.py` | LLM dispatch: rotation chain, fallback chain, JSON parsing, `_fix_json_escapes`, `_extract_json_object` |
| `api/services/sandbox_service.py` | Docker container helpers: class detection, SQLite setup, code placement, route scaffolding, Pest/mutation execution, covers() injection |
| `api/services/patch_service.py` | Applies `full_replace` / `create_file` patches; enforces forbidden file blocklist; strips markdown fences |
| `api/services/boost_service.py` | Queries Laravel schema, routes, and docs from inside the container; keyed by `(submission_id, component_type)` to prevent cross-submission cache contamination |
| `api/services/escalation_service.py` | 4-rule stuck-loop detector: repeated diagnoses, patch failures, create_file without fixing original, Dependency Guard |
| `api/services/context_service.py` | 200-item sliding window memory: stores successful repairs, retrieves top-3 similar past fixes using `SequenceMatcher` + efficiency weighting |
| `api/services/docker_service.py` | Low-level Docker exec/copy/destroy primitives |
| `api/services/evaluation_service.py` | Batch evaluation orchestrator — iterates over `batch_manifest.yaml`, persists CSV |

---

## 4. What Succeeded ✅

| Feature | File(s) | Status |
|---|---|---|
| Docker sandbox isolation per submission | `docker_service.py` | ✅ |
| Multi-patch `full_replace` + `create_file` architecture | `patch_service.py`, `repair_service.py` | ✅ |
| Forbidden file blocklist (routes/api.php etc.) | `patch_service.py` FORBIDDEN_FILENAMES | ✅ |
| 4-model rotation (Qwen→DeepSeek→Llama→Gemini) | `ai_service.py` ROTATION_CHAIN | ✅ |
| Provider fallback chain (Nvidia→Dashscope→Groq→Cerebras→Gemini) | `ai_service.py` FALLBACK_CHAIN | ✅ |
| Per-iteration `ai_model_used` tracked in DB + CSV | `repair_service.py` _save_iteration | ✅ |
| Pest 3 baseline HTTP gate | `sandbox_service.py` generate_baseline_pest_test | ✅ |
| Mutation testing gate with `covers()` enforcement | `sandbox_service.py` ensure_covers_directive | ✅ |
| AI test syntax lint before mutation gate | `sandbox_service.py` lint_test_file | ✅ |
| Soft-pass for infra failures (pcov/Unknown option) | `sandbox_service.py` run_mutation_test | ✅ |
| Partial mutation score persisted even on failed iterations | `repair_service.py` iter_mutation_score | ✅ |
| Boost schema + route context injection | `boost_service.py` | ✅ |
| Boost cache keyed by (submission_id, component_type) | `boost_service.py` | ✅ |
| Boost noise filtering (strips default Laravel tables/routes) | `boost_service.py` | ✅ |
| Route scaffolded BEFORE boost query | `repair_service.py` step 5 before step 6 | ✅ |
| Smart component detection (scoring-based, not if/elif) | `boost_service.py` | ✅ |
| 4-rule escalation triggers incl. Dependency Guard | `escalation_service.py` | ✅ |
| Sliding 200-item fuzzy memory (RL-weighted retrieval) | `context_service.py` | ✅ |
| Feedback loop — AI sees previous iteration outcomes | `ai_service.py` _build_prompt | ✅ |
| JSON escape hell fix (PHP namespace backslashes) | `ai_service.py` _fix_json_escapes | ✅ |
| `<think>...</think>` stripping for DeepSeek R1 | `ai_service.py` _extract_json_object | ✅ |
| BOM + CRLF normalization | `repair_service.py` _normalize_code | ✅ |
| Named-class migration → anonymous class normalization | `repair_service.py` _normalize_migration | ✅ |
| Laravel app log capture (last 40 lines) on Pest failure | `sandbox_service.py` capture_laravel_log | ✅ |
| TEST_DEPENDENCY_ERROR tagging for missing class/factory | `repair_service.py` crash_markers | ✅ |
| User prompt elevated in prompt hierarchy | `ai_service.py` _build_prompt | ✅ |
| Spatie PHP coding standards in system prompt | `api/prompts/repair_prompt.md` | ✅ |
| Batch evaluation pipeline + CSV reporting | `evaluation_service.py` | ✅ |
| SSE real-time streaming to frontend | `repair_service.py` yield _evt() | ✅ |
| Rate limiting, auth token, CORS | `main.py`, `limiter.py`, `auth_service.py` | ✅ |
| Unified logging: console + rotating file + submission_id context | `logging_config.py`, `main.py` | ✅ |
| `UnboundLocalError` crash fix in mutation failure branch | `repair_service.py` L226 `error_text` ref guard | ✅ |
| `patch_result` variable scoped before `previous_attempts.append` | `repair_service.py` L364 | ✅ |

---

## 5. Persistent Failures — What Has Consistently Broken

These are the issues that have recurred across **multiple sessions** and have never been fully resolved end-to-end.

### 5.1 🔴 Log Visibility — The Biggest Complaint

**Problem:** Logs are written to `data/logs/repair_platform.log` and to the console via `logging_config.py`. Despite the config being correct on paper, in practice:

- The `submission_id` field in log lines often shows `"Global"` instead of the actual UUID because most log calls in inner services (`boost_service.py`, `docker_service.py`, `patch_service.py`) use a plain `logger.info(...)` call — **not** a `LoggerAdapter` with the `submission_id` extra. Only `repair_service.py` creates a `ctx_log = logging.LoggerAdapter(logger, {"submission_id": submission_id})`, but this adapter is never passed down into child service calls.
- **Net effect:** You cannot trace a specific repair attempt end-to-end in the log file by filtering on `submission_id`. The field is present in the format string but populated as `"Global"` for ~90% of lines.
- **Root cause:** The `LoggerAdapter` is local to `repair_service.py`. Every other service has its own module-level `logger = logging.getLogger(__name__)` which has no `submission_id` bound.
- **Fix required:** Either pass `ctx_log` into every service function as a parameter, or use Python's `contextvars.ContextVar` to propagate `submission_id` into a custom logging `Filter` that injects it automatically.

### 5.2 🔴 `error_text` UnboundLocalError (Intermittent, Partially Fixed)

**Problem:** In the mutation failure branch (lines 224–234 of `repair_service.py`), `error_text` is referenced at line 226 before it is guaranteed to be defined if the code entered the mutation section via the `is_genuine = True` / `current_pest_test` branch where `error_text` was never set in that iteration's scope.

**Current state:** A fix was applied in conversation `dc5d3914` to guard against this, but the guard is fragile. The variable `error_text` is assigned in multiple branches of the iteration's `if/else` tree, and a future refactor of that tree could re-introduce the bug. There is no single point of initialization to `error_text = ""` at the top of the iteration loop body.

**Fix required:** Add `error_text = ""` at the very top of the `for iteration_num in range(max_iter):` loop body (before the inner `try:` block) so it is always defined.

### 5.3 🔴 `patch_result` Used Outside Its Scope

**Problem:** At `repair_service.py` line 364:
```python
"created_files": list(patch_result.created_files.keys()) if patch_status == "applied" else [],
```
`patch_result` is only assigned inside the `try` block of the patch section. If a `PatchApplicationError` is raised (setting `patch_status = "FAILED — ..."`) before `patch_result` is assigned, this line will raise a `NameError: name 'patch_result' is not defined`.

**Current state:** The `if patch_status == "applied"` guard partially protects this, but only because `PatchApplicationError` is raised inside `patch_service.apply_all()` which is what assigns `patch_result`. If `apply_all` raises before returning, `patch_result` is never set.

**Fix required:** Initialize `patch_result = None` before the patch `try` block and adjust line 364 to `list(patch_result.created_files.keys()) if patch_result is not None else []`.

### 5.4 🔴 Mutation Score Parser — Silent Zero Returns

**Problem:** `parse_mutation_score()` in `sandbox_service.py` uses 6 regex patterns. If Pest's `--mutate` output format changes slightly (e.g., different ANSI codes, or a new version changes the summary line structure), all 6 patterns can fail, and the function silently returns `0.0` with only a WARNING log. A score of 0.0 causes the iteration to be treated as a mutation failure — triggering another repair iteration unnecessarily.

**Current state:** There is a `logger.warning()` on no-match, but no SSE event is emitted to the frontend. The user sees a mutation score of 0% with no explanation.

**Fix required:** When no pattern matches, emit an `_evt("log_line", ...)` to the SSE stream explaining that the mutation parser could not extract a score and is treating it as 0%.

### 5.5 🟡 Docker Timeout Under WSL — Resource Limits

**Problem:** Heavy PHP operations inside the Docker container (especially `composer dump-autoload`, `php artisan migrate`, and mutation testing) frequently hit the `CONTAINER_TIMEOUT_SECONDS` ceiling under WSL, causing `asyncio.TimeoutError` exceptions that propagate as iteration crashes rather than clean error messages.

**Current state:** `.env` has `CONTAINER_TIMEOUT_SECONDS` tuned, and individual Docker exec calls use per-command `timeout=` values, but the values chosen were conservative and the mutation test timeout (120 s) has been hit repeatedly on slower WSL configurations.

**Fix required:** Make mutation test timeout separately configurable in `.env` (e.g., `MUTATION_TIMEOUT_SECONDS=180`) rather than hardcoded to `120` in `sandbox_service.py` line 253.

### 5.6 🟡 Batch Evaluation — No Parallelism

**Problem:** The batch evaluator in `evaluation_service.py` processes cases sequentially. A 10-case manifest with 4-iteration repairs takes ~40+ minutes. Every Docker container is spun up and torn down serially.

**Root cause:** Both the Docker daemon interaction and SQLite writes are not safe to parallelize without connection pooling and mutex guards.

**Current state:** Acknowledged as a known limitation but not addressed. Batch runs for the thesis remain very slow.

### 5.7 🟡 Frontend (LaraVibe FE) — Not Integrated End-to-End

**Problem:** The `laravibe-fe/` directory exists and the SSE endpoint works. However, the frontend has never been tested against a live backend in WSL from the Windows host. The CORS policy is `allow_origins=["*"]` (permissive), but the actual connection from the Next.js dev server on Windows to uvicorn in WSL on `localhost:8000` has not been validated.

### 5.8 🟡 `RepairSummary.what_did_not_work` Column Missing from Old DB

**Problem:** If the SQLite database was created before the `what_did_not_work` column was added to `RepairSummary`, the column doesn't exist in the on-disk schema. SQLAlchemy will silently succeed on reads (returning `None`) but crash on writes if the column is absent.

**Fix required:** A migration script or a `CREATE TABLE IF NOT EXIST` guard with `ALTER TABLE` for the column if it's missing.

### 5.9 🟡 `ensure_covers_directive` — Incorrect FQCN Double-Backslash

**Problem:** In `sandbox_service.py` line 443:
```python
target_fqcn = f"\\\\{ns_match.group(1).strip()}\\\\{class_name}"
```
This produces `\\App\\Http\\Controllers\\UserController` (double backslash) in the Python string, which when written into PHP becomes `\\App\\Http\\Controllers\\UserController`. The correct PHP for `covers()` is `\App\Http\Controllers\UserController::class` (single backslash). The double-backslash fallback path may inject a syntactically wrong `covers()` call, causing the Pest test to fail the lint gate even though the AI wrote correct code.

---

## 6. What Was NOT Built (Known Scope Gaps)

| Gap | Reason |
|---|---|
| Vector-based semantic memory | Requires embedding model infra (too heavy for this phase) |
| Parallel batch evaluation | Hard to parallelise with single Docker daemon + SQLite |
| Auto-test case generation from spec | Out of scope — user provides dataset |
| Fine-tuned PHP repair model | Would need GPU infra + labelled dataset |
| Frontend live report page | LaraVibe FE exists but full WSL↔Windows integration not tested |
| `submission_id` propagated into child service logs | Requires `contextvars` refactor or parameter threading |

---

## 7. The `.env` File — Clarification

| Setting | Effect |
|---|---|
| `DEFAULT_AI_PROVIDER=fallback` | Used for single REST API submissions (`POST /api/repair`). Picks first working provider from `FALLBACK_CHAIN`. |
| `AI_MODEL=...` | Only used when `DEFAULT_AI_PROVIDER` is set to a specific single provider (not `fallback`). |
| During batch evaluation | `ROTATION_CHAIN` in `ai_service.py` takes over entirely, overriding `.env` values per iteration. |
| `CONTAINER_TIMEOUT_SECONDS` | Global default. Individual exec calls can override. Mutation test is hardcoded 120s — not controlled by this setting. |

---

## 8. WSL Commands to Start & Run

```bash
# 1. Activate virtualenv
source venv/bin/activate

# 2. Start the FastAPI backend
uvicorn api.main:app --reload --port 8000

# 3. Run a single case (separate terminal, same venv)
python scratch_test_case.py

# 4. Trigger a batch evaluation
curl -X POST http://localhost:8000/api/evaluate \
  -H "Content-Type: application/json" \
  -H "X-Repair-Token: change-me-in-production" \
  -d '{"manifest_path": "batch_manifest.yaml", "batch_id": "thesis-run-01"}'

# 5. Analyze results
python scratch_analyze.py

# 6. View live log
tail -f data/logs/repair_platform.log
```

---

## 9. How the Tricky Parts Were Made to Work

| Problem | Solution |
|---|---|
| Mutation soft-pass bug | Infection exit code without `covers()` → detected, treated as score=0 fail (not soft-pass) |
| JSON escape hell | `_fix_json_escapes()` regex pre-processor before `json.loads()` |
| BOM characters | `_normalize_code()` strips `\ufeff` prefix |
| CRLF line endings | `_normalize_code()` normalizes to `\n` |
| Named-class migration redeclaration | `_normalize_migration()` converts to anonymous class syntax |
| Route registration before boost | `scaffold_route()` is called before `boost_service.query_context()` so `route:list` sees the route |
| Cross-submission cache contamination | Boost cache keyed on `(submission_id, component_type)` |
| AI re-creating already-existing files | Dependency Guard in `escalation_service.py` detects duplicate `create_file` paths |
| `<think>` blocks in DeepSeek R1 | Stripped by regex in `_extract_json_object()` before brace-depth parsing |
| AI wrapping single patch as dict not list | `_parse_response()` normalizes `isinstance(patches_data, dict)` case |
| AI using wrong key (`filename` vs `target`) | `apply_all` resolves `filename or target or path` from patch dict |

---

## 10. Research Data Produced

Every iteration (success or fail) produces:

- A **SQLite `Iteration` row**: code, error, boost context, AI prompt, AI response, model used, mutation score, duration.
- A **SQLite `Submission` row**: final status, final code, total iterations.
- A **SQLite `RepairSummary` row** (on success only): error signature, diagnosis, fix applied, dead-ends, iterations needed.
- A **CSV row** in `data/results/` summarising the above per submission.

This dataset enables ablation studies:

- Provider efficiency (which model needed fewest iterations?)
- Error category success rates (BOM vs namespace vs missing dependency)
- Boost impact (boost_on vs boost_off manifests)
- Mutation score distributions across error categories

---

## 11. Priority Fix List (Ranked)

| # | Issue | Severity | File | Est. Effort |
|---|---|---|---|---|
| 1 | `submission_id` not propagated into child service logs | 🔴 High | All services | Medium (contextvars refactor) |
| 2 | `error_text` potentially unbound in mutation failure branch | 🔴 High | `repair_service.py` | Trivial (1 line init) |
| 3 | `patch_result` potentially unbound on PatchApplicationError | 🔴 High | `repair_service.py` | Trivial (1 line init) |
| 4 | `ensure_covers_directive` double-backslash FQCN bug | 🟡 Medium | `sandbox_service.py` | Small |
| 5 | Mutation score parser silent zero — no SSE event | 🟡 Medium | `sandbox_service.py` | Small |
| 6 | Mutation test timeout not `.env` configurable | 🟡 Medium | `sandbox_service.py` | Small |
| 7 | `RepairSummary.what_did_not_work` missing column guard | 🟡 Medium | DB migration | Small |
| 8 | Frontend WSL↔Windows integration test | 🟡 Medium | `laravibe-fe/` | Medium |
