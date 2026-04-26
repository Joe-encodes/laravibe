# LaraVibe Backend: Technical Architecture & Logic Deep-Dive

**Last updated:** 2026-04-22  
This document provides a low-level technical specification of the LaraVibe (Laravel AI Repair Platform) backend. It focuses exclusively on the FastAPI coordinator, its service layer, and the iterative repair mechanics. All details reflect the **actual running codebase** as of the date above.

---

## 1. Core Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| **Framework** | FastAPI 0.115+ (Python 3.12) | Async ASGI via Uvicorn |
| **Async Engine** | `asyncio` | All Docker exec, AI calls, and DB writes are non-blocking |
| **ORM** | SQLAlchemy 2.0 + `aiosqlite` | Async SQLite; `create_tables()` called at lifespan startup |
| **Validation** | Pydantic v2 | Request/response schemas in `schemas.py`; env settings via `pydantic-settings` in `config.py` |
| **Sandbox** | Docker Python SDK | `docker_service.py` wraps all container lifecycle calls in `asyncio.run_in_executor()` |
| **AI Routing** | Custom multi-provider dispatcher | `ROTATION_CHAIN` (batch) + `FALLBACK_CHAIN` (single) — no LiteLLM proxy |
| **Reliability** | `tenacity` | 3 retries on `ValueError`/`JSONDecodeError`; 3 retries on network/rate-limit errors with exponential backoff (max 10 s) |
| **Rate Limiting** | `slowapi` | Applied at router level; `RateLimitExceeded` handler registered on the app |
| **Logging** | Python `logging` + `RotatingFileHandler` | Console + `data/logs/repair_platform.log` (10 MB × 5 backups) |

---

## 2. Global Request-Response Lifecycle

Every repair request follows a non-blocking, asynchronous lifecycle:

1. **Ingress (`POST /api/repair`)**
   - Validates PHP code (non-empty, within `MAX_CODE_SIZE_KB`).
   - Persists original code to the `submissions` table (`status=pending`).
   - Spawns a **FastAPI `BackgroundTask`** to run the orchestration loop.
   - Returns `202 Accepted` with `submission_id` immediately.

2. **Streaming (`GET /api/repair/{id}/stream`)**
   - Client connects via **Server-Sent Events (SSE)**.
   - `repair_service.run_repair_loop()` is an `AsyncGenerator` that yields JSON event dicts.
   - The SSE router consumes the generator and formats each dict as a `data: {...}` line.

3. **Process Completion**
   - `_save_iteration()` persists each iteration record to the `iterations` table.
   - The `Submission` row is updated to `success` or `failed`.
   - A `complete` event is emitted as the final SSE message, closing the stream.

---

## 3. Data Infrastructure (Models & Schemas)

### Entity-Relationship Model

```
submissions (1) ──────< iterations (N)
submissions (1) ──────< repair_summaries (N, on success only)
```

- **`Submission`**: Root record tracking global state (`pending → running → success / failed`), research metadata (`case_id`, `category`, `experiment_id`), and final repaired code.
- **`Iteration`**: Linked 1:N to Submission. Stores every snapshot per repair cycle.
- **`RepairSummary`**: Stores successful repairs for the sliding-window memory. Populated only on success.

### Key Fields — `iterations` Table

| Field | Type | Role |
|---|---|---|
| `boost_context` | Text (JSON) | Exact Boost context snapshot used in that iteration |
| `ai_prompt` | Text | The full assembled prompt sent to the LLM |
| `ai_response` | Text | Raw LLM response JSON (before parsing) |
| `ai_model_used` | String(100) | Actual provider/model that generated the response (e.g. `nvidia/Qwen/Qwen2.5-Coder-32B-Instruct`) |
| `patch_applied` | Text | Stringified list of `PatchSpec` objects (action + filename + replacement) |
| `mutation_score` | Float | Percentage (0.0–100.0) from `pest --mutate`; `NULL` if gate not reached |
| `error_logs` | Text | Combined stderr + stdout from the failed exec or test run, including captured Laravel log tail |

### Key Fields — `submissions` Table

| Field | Role |
|---|---|
| `user_id` | Optional — for multi-user deployments |
| `user_prompt` | Optional extra instructions submitted alongside code |
| `case_id` / `category` / `experiment_id` | Batch evaluation metadata for ablation studies |

---

## 4. Service Architecture Deep-Dive

### A. `docker_service.py` — The Sandbox

Managed via the Docker Python SDK. All blocking calls are offloaded to `asyncio.run_in_executor()`.

**Security constraints applied at container creation:**
```python
network_mode="none"                          # Zero internet access
mem_limit="512m"                             # OOM attack prevention
nano_cpus=int(0.5 * 1e9)                     # 0.5 CPU — restricts CPU hogs
pids_limit=64                                # Fork bomb prevention
security_opt=["no-new-privileges:true"]      # Privilege escalation blocked
```

**Key primitives:**

| Function | Behaviour |
|---|---|
| `create_container()` | Spawns a fresh container; returns the Docker SDK container object |
| `copy_code(container, code)` | Writes PHP to `/submitted/code.php` via in-memory tar stream — no host temp files |
| `copy_file(container, path, content)` | General-purpose file injection (used for models, migrations, Pest tests) |
| `execute(container, cmd, timeout, user)` | Runs a shell command; returns `ExecResult(stdout, stderr, exit_code, duration_ms)` |
| `ping(container)` | Health check — confirms container is responsive before starting the repair loop |
| `destroy(container)` | Stop + remove; always called in `finally` block — zero container leaks |

`ExecResult.has_php_fatal` catches PHP fatal errors that emit a zero exit code — a well-known PHP inconsistency.

---

### B. `sandbox_service.py` — Laravel Interaction Helpers

Extracted from `repair_service.py` to keep the orchestrator lean. Each function does exactly one thing inside the running container.

| Function | What It Does |
|---|---|
| `detect_class_info(container)` | Parses namespace + classname from `code.php` via PHP one-liners; builds `ClassInfo` (FQCN, PSR-4 dest path, route resource name) |
| `setup_sqlite(container)` | Switches the sandbox to SQLite (needed because `--network=none` blocks MySQL); runs `php artisan migrate --force` |
| `place_code_in_laravel(container, class_info)` | Copies code to the correct PSR-4 path, runs `composer dump-autoload`, validates via Tinker; normalises exit code by `CLASS_OK` sentinel |
| `scaffold_route(container, class_info)` | Appends `Route::apiResource()` to `routes/api.php` idempotently — runs **before** Boost so `route:list` sees the new route |
| `run_pest_test(container)` | Runs `./vendor/bin/pest --filter=RepairTest --no-coverage` |
| `capture_laravel_log(container)` | Reads last 40 lines of `storage/logs/laravel.log` — surfaces the real PHP exception behind a Pest failure |
| `run_mutation_test(container)` | Runs `./vendor/bin/pest --mutate`; parses score; classifies output into: `covers_missing` (score=0, fail), `dependency_failure` (score=0, fail), `infra_failure` (soft-pass), or real score |
| `parse_mutation_score(output)` | 6-pattern regex suite with ANSI stripping; returns `0.0` if no pattern matches |
| `lint_test_file(container)` | Runs `php -l` on `RepairTest.php` before the mutation gate — catches AI-generated syntax errors early |
| `generate_baseline_pest_test(class_info)` | Generates a system-controlled HTTP assertion test (`getJson('/api/{resource}')->assertSuccessful()`) |
| `inject_pest_test(container, code)` | Writes the Pest test to `tests/Feature/RepairTest.php` |
| `ensure_covers_directive(pest_test, code, fqcn)` | Injects missing `use function Pest\Laravel\{...};` imports and a `covers(ClassName::class);` directive for mutation gate validity |
| `reinject_files(container, files)` | Re-injects supplementary files (models, migrations) created in earlier iterations into the current container |

---

### C. `boost_service.py` — Context Engine

Exposes the internal Laravel application state to the AI prompt. Runs artisan commands **inside the sandbox container** so it sees the exact project at that point in the repair cycle.

**Priority Fallback Chain:**
```
boost:schema (Laravel Boost)  →  db:show (native Laravel)  →  find app/Models  →  empty
boost:docs   (Laravel Boost)  →  (no fallback, skipped)
route:list   (always run)     →  routes/api.php raw content (always appended)
```

**Cache:** Keyed by `SHA-256(submission_id + framework_version + component_type)` — **not** by raw error text. This means:
- Multiple iterations in the same submission that hit the same component type share a cache entry.
- Batch runs with different `submission_id` values never contaminate each other.

**Component Detection (`_detect_component_type`):** Score-based (not `if/elif`). Error text is scanned for weighted keywords across 6 component types (`controller`, `model`, `migration`, `middleware`, `route`, `request`). The highest-scoring type wins. Ties default to the more specific type.

**Noise Filtering (`to_prompt_text`):** Strips Laravel's default tables (`cache`, `sessions`, `failed_jobs`, etc.) and internal Boost/Sanctum routes before building the prompt text. This reduces token waste and prevents the AI from being distracted by framework boilerplate.

---

### D. `ai_service.py` — LLM Dispatcher

**Model Chains:**

```python
# Used during batch evaluation — rotates cognitive diversity per iteration
ROTATION_CHAIN = [
    ("nvidia",    "Qwen/Qwen2.5-Coder-32B-Instruct"),   # Iteration 0
    ("dashscope", "deepseek-v3"),                        # Iteration 1
    ("nvidia",    "meta/llama-3.3-70b-instruct"),        # Iteration 2
    ("gemini",    "gemini-2.5-flash"),                   # Iteration 3
]

# Used when DEFAULT_AI_PROVIDER=fallback (single submissions)
FALLBACK_CHAIN = [
    ("nvidia",    "meta/llama-3.3-70b-instruct"),
    ("nvidia",    "Qwen/Qwen2.5-72B-Instruct"),
    ("dashscope", "deepseek-v3"),
    ("dashscope", "qwen-max"),
    ("groq",      "llama-3.3-70b-versatile"),
    ("cerebras",  "llama-3.3-70b"),
    ("gemini",    "gemini-2.0-flash"),
    ("gemini",    "gemini-2.5-flash"),
]
```

**Prompt Assembly (`_build_prompt`):** Uses `.replace()` on the `repair_prompt.md` template — never f-strings, because PHP code contains `{}` which would crash f-string parsing. Fields injected:
- `{code}` — current code string
- `{error}` — runtime error text (may include Laravel log tail and `TEST_DEPENDENCY_ERROR` prefix)
- `{boost_context}` — Boost prompt text
- `{escalation_context}` — stuck-loop instructions from `escalation_service`
- `{user_prompt}` — optional user instruction elevated in hierarchy
- `{previous_attempts}` — all prior iteration outcomes (action, diagnosis, fix, outcome)
- `{similar_past_repairs}` — top-3 similar repairs from `context_service`

**JSON Recovery Pipeline (`_extract_json_object`):**
1. Strip `<think>...</think>` blocks (DeepSeek R1 chain-of-thought).
2. Find first `{` in the cleaned text.
3. Walk forward with brace-depth tracking, respecting string boundaries and escape sequences.
4. Return the balanced JSON object — handles prose before/after, markdown fences, and nested structures.

**`_fix_json_escapes`:** Repairs single backslashes in PHP namespace strings (`App\Models\Product`) that break `json.loads()`. Uses a negative-lookbehind regex to avoid double-escaping already-correct sequences.

**JSON Mode:** `response_format={"type": "json_object"}` is activated for providers that support it natively (`openai`, `deepseek`, `groq`, `nvidia`, `qwen`, `dashscope`). Gemini and Cerebras receive it via prompt instruction only.

**`model_used` tracking:** Every successful call returns `(response_text, "provider/model")`. This string is stored in `ai_model_used` on the `Iteration` record — critical for per-model performance analysis in the thesis dataset.

---

### E. `patch_service.py` — Code Mutation

**Supported actions:**

| Action | Behaviour |
|---|---|
| `full_replace` | Replaces the **entire** file content with `replacement`. Mandatory for the submitted controller/class file. |
| `create_file` | Returns `current_code` unchanged; signals `repair_service` to write `filename` as a new file to the container. |
| `replace` / `append` | **Banned.** Raises `PatchApplicationError` immediately — legacy actions removed to prevent partial patch failures. |

**Forbidden file blocklist (`FORBIDDEN_FILENAMES`):**
```python
{"routes/api.php", "routes/web.php", "routes/console.php", "routes/channels.php"}
```
Route files are managed exclusively by `sandbox_service.scaffold_route()`. Any AI `create_file` targeting these is blocked with a `log_line` SSE event and added to `patch_result.skipped_forbidden`.

**`apply_all(current_code, patches)`:** Processes a list of `PatchSpec` objects in order. Returns `ApplyAllResult` containing:
- `updated_code` — the new main file content after `full_replace` patches
- `created_files` — `{rel_path: content}` dict for files the loop must write to the container
- `actions_taken` — list of action strings (used for `patch_applied` SSE event and `previous_attempts` tracking)
- `skipped_forbidden` — list of blocked filenames

---

### F. `escalation_service.py` — Stuck Loop Detection

Detects when the LLM is stuck and injects stern corrective instructions into the next iteration's prompt. Four independent triggers evaluated after every failed iteration:

| Trigger | Condition | Injected Message |
|---|---|---|
| 1. Stuck Diagnoses | Last 2 diagnoses are fuzzy-identical (≥ 70% word overlap) | Forces completely different reasoning strategy |
| 2. Patch Failures | Last 2 patches both failed to apply | Forces `full_replace` — bans `replace` action |
| 3. Create-without-Fix | Last action was `create_file` without `full_replace` | Tells AI the dependency file now exists; demands a `full_replace` of the original file |
| 4. Dependency Guard | Same file path appears in `created_files` more than once | Explicitly names the already-existing files; forbids re-creating them |

---

### G. `context_service.py` — Sliding Window Memory

Implements a lightweight retrieval-augmented generation (RAG) layer using a 200-item in-process `deque`.

**Storage (on success):** `store_repair_summary()` persists a `RepairSummary` row and appends to the deque immediately — no cold-start delay for the current session.

**Retrieval:** `retrieve_similar_repairs()` scores every cached entry using:
```
retrieval_score = (similarity × 0.7) + (efficiency × 0.3)
where:
  similarity = SequenceMatcher ratio of error signatures
  efficiency = 1 / iterations_needed
```
Top-3 matches above the 0.6 similarity threshold are formatted as a prompt addendum showing what worked and what dead ends to avoid.

**Error Signature Extraction (`_extract_error_signature`):** Normalises raw error text to a short canonical key using a 4-level priority chain:
1. `local.ERROR:` Laravel app log exception (most specific)
2. `Exception:` PHP exception message
3. `Fatal error:` PHP fatal error
4. First non-empty, non-separator line (fallback)

**Cold Start:** The deque is populated from the DB on the first `retrieve_similar_repairs()` call (`_ensure_cache_loaded()`). Subsequent calls are O(1) guard.

---

### H. `repair_service.py` — The Orchestrator

The main `async def run_repair_loop()` generator. 413 lines. Key design decisions:

**Container lifecycle:** One container is created **before** the iteration loop and destroyed in `finally`. This is the V2 "persistent container" model — supplementary files created in iteration N are naturally present in iteration N+1. No re-injection needed.

> **Note on `reinject_files`:** `sandbox_service.reinject_files()` still exists but is not called in the current main loop. It is preserved for the legacy V1 per-iteration fresh-container model.

**Iteration sequence (13 steps):**
```
1.  copy_code()
2.  php -l lint gate
3.  detect_class_info()
4.  place_code_in_laravel()
5.  scaffold_route()          ← BEFORE boost (so route:list sees the route)
6.  boost_service.query_context()
7.  context_service.retrieve_similar_repairs()
8.  escalation_service.build_escalation_context()
9.  ai_service.get_repair()
10. sandbox_service.ensure_covers_directive()
11. patch_service.apply_all()
12. run_pest_test()
13. run_mutation_test() (only if AI test present and is_genuine=False)
```

**`_normalize_code()`:** Strips CRLF (`\r\n` → `\n`) and UTF-8 BOM (`\ufeff`) from submitted code. Applied once on the raw submission.

**`_normalize_migration()`:** Converts named-class migrations (`class Foo extends Migration {}`) to anonymous-class syntax (`return new class extends Migration {};`). Prevents `Cannot redeclare class` fatal errors during iterative loops.

**`iter_mutation_score` tracking:** Even when an iteration fails the mutation gate, the partial score is stored in `mutation_score` on the `Iteration` record. This ensures every iteration in the research dataset has a score field, enabling full distribution analysis.

**Laravel log capture:** On Pest failure, `capture_laravel_log()` fetches the last 40 lines of `storage/logs/laravel.log` and appends it to `error_text`. This surfaces the real PHP exception (e.g. `Class App\Models\Product not found`) that Pest's own output often hides.

**`TEST_DEPENDENCY_ERROR` tagging:** If the Pest failure output contains `not found`, `doesn't exist`, `ReflectionException`, or `Call to undefined method`, the error is prefixed with `TEST_DEPENDENCY_ERROR:`. This keyword instructs the AI to use `create_file` rather than a `full_replace`.

---

## 5. The Iterative Loop — State Machine

The loop runs up to `MAX_ITERATIONS` (default 4, configurable via `.env`). The container persists across all iterations.

```
┌─────────────────────────────────────────────────────┐
│                   ITERATION START                   │
│                                                     │
│  copy code → lint → detect class → place in Laravel │
│  scaffold route → boost query                       │
│                                                     │
│  ┌── exec ok? ──────────────────────────────────┐  │
│  │ YES: generate baseline test → run Pest        │  │
│  │      ┌── Pest pass? ──────────────────────┐  │  │
│  │      │ YES: if AI test exists → run mutate │  │  │
│  │      │      if mutate ≥ threshold → SUCCESS│  │  │
│  │      │      else → set error_text, continue│  │  │
│  │      │ NO:  capture Laravel log → error_text│  │  │
│  │      └───────────────────────────────────── ┘  │  │
│  │ NO:  set error_text from exec stderr            │  │
│  └─────────────────────────────────────────────────┘  │
│                                                     │
│  → boost query → retrieve memory → escalation check │
│  → call AI → apply patches → save iteration        │
│  → loop back (or exhaust)                          │
└─────────────────────────────────────────────────────┘
```

**Stopping conditions:**

| Condition | Outcome |
|---|---|
| `exec OK` + `Pest pass` + `mutation ≥ threshold` | `SUCCESS` — store `RepairSummary`, emit `complete(status=success)` |
| `exec OK` + `Pest pass` + no AI test yet | `SUCCESS` (baseline pass accepted without mutation gate) |
| `create_file` mutation override | `SUCCESS` (0% accepted if last action was `create_file`) |
| All iterations exhausted | `FAILED` — emit `complete(status=failed)` |
| `AIServiceError` raised | `FAILED` immediately — all fallback providers exhausted |

---

## 6. API Endpoint Specification

All endpoints requiring auth use `Authorization: Bearer <X-Repair-Token>` from `.env`.

### `POST /api/repair`
- **Accepts**: `RepairRequest` (`code`, `max_iterations`, `use_boost`, `use_mutation_gate`, `prompt`)
- **Returns**: `202 Accepted` + `submission_id`
- **Background**: Immediately starts `run_repair_loop()` as a FastAPI `BackgroundTask`

### `GET /api/repair/{id}/stream`
- **Protocol**: Server-Sent Events (SSE)
- **Event types**: `submission_start`, `iteration_start`, `log_line`, `boost_queried`, `ai_thinking`, `pest_result`, `mutation_result`, `patch_applied`, `error`, `complete`
- **FE note**: `log_line` events with 🔄 indicate provider fallback in progress. Do NOT close the `EventSource` on seeing these — the loop continues.

### `GET /api/repair/{id}`
- Returns `SubmissionOut` with full nested `iterations` array including all stored fields.

### `GET /api/history`
- Returns 50 most recent `SubmissionOut` objects (without iteration detail).

### `POST /api/evaluate`
- Triggers batch evaluation from `batch_manifest.yaml`.
- Runs cases sequentially (Docker + SQLite constraints prevent parallelism).

### `GET /api/health`
- Returns Docker, AI key, and DB connectivity status.

### `GET /api/stats`
- Returns aggregate statistics: success rate, average iterations, mutation score distribution.

### `DELETE /api/admin/submissions/{id}`
- Admin endpoint — hard-deletes a submission and its iterations (cascade).

---

## 7. Configuration & Empirical Evaluation Framework

### `.env` Key Settings

| Variable | Governs |
|---|---|
| `DEFAULT_AI_PROVIDER` | `fallback` = single-submission FALLBACK_CHAIN; specific name = single provider |
| `AI_MODEL` | Only used when `DEFAULT_AI_PROVIDER` is not `fallback` |
| `AI_TEMPERATURE` | Fixed at `0.0` for all thesis evaluation runs |
| `MAX_ITERATIONS` | Default `4`; overridable per-request |
| `MUTATION_SCORE_THRESHOLD` | Default `80` (percent) |
| `CONTAINER_TIMEOUT_SECONDS` | Default exec timeout; mutation test is hardcoded 120 s separately |
| `REPAIR_TOKEN` | Bearer token for auth-required endpoints |

> **Important:** During batch evaluation, `ROTATION_CHAIN` in `ai_service.py` overrides `DEFAULT_AI_PROVIDER` and `AI_MODEL` entirely. `.env` provider settings only govern direct `POST /api/repair` calls.

### Ablation Study Support

`batch_manifest.yaml` exposes two flags per run:

| Flag | What It Measures When Disabled |
|---|---|
| `use_boost_context: false` | Boost's contribution to repair success rate |
| `use_mutation_gate: false` | Mutation gate's contribution to fix quality |

### Metrics Captured Per Iteration

| Metric | DB Column | CSV |
|---|---|---|
| Success / Fail | `iterations.status` | ✅ |
| Iteration count | `submissions.total_iterations` | ✅ |
| Mutation score | `iterations.mutation_score` | ✅ |
| Model used | `iterations.ai_model_used` | ✅ |
| Duration | `iterations.duration_ms` | ✅ |
| Boost context present | `iterations.boost_context` (non-null) | ✅ |

