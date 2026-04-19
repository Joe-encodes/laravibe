# LaraVibe Backend: Technical Architecture & Logic Deep-Dive

This document provides a low-level technical specification of the LaraVibe (Laravel AI Repair Platform) backend. It focuses exclusively on the FastAPI coordinator, its service layer, and the iterative repair mechanics.

---

## 1. Core Technology Stack

- **Framework**: [FastAPI 0.115+](https://fastapi.tiangolo.com/) (Python 3.12)
- **Asynchronous Engine**: `asyncio` for non-blocking I/O (Docker exec, AI calls, DB).
- **ORM**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with `aiosqlite` (Async SQLite).
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/latest/) for request/response schemas and environment settings.
- **Orchestration**: [Docker Python SDK](https://docker-py.readthedocs.io/) for sandbox lifecycle management.
- **AI Integration**: Multi-provider LiteLLM-style fallback routing (`FALLBACK_CHAIN`) supporting Nvidia (Deepseek), Cerebras, Groq, Dashscope, Gemini, and Local Ollama natively without a proxy proxy.
- **Reliability**: `tenacity` for strict API rate limit backoff (fails-fast to next model) and robust JSON recovery.

---

## 2. Global Request-Response Lifecycle

Every repair request follows a non-blocking, asynchronous lifecycle:

1.  **Ingress (`POST /api/repair`)**:
    - Validates PHP code (ensures `<?php` header).
    - Persists original code to the `submissions` table (`status=pending`).
    - Spawns a **FastAPI Background Task** to run the orchestration loop.
    - Returns a `202 Accepted` with a `submission_id`.
2.  **Streaming (`GET /api/repair/{id}/stream`)**:
    - Client connects via **Server-Sent Events (SSE)**.
    - The `repair_service` acts as an `AsyncGenerator`, yielding events (JSON) as they happen.
3.  **Process Completion**:
    - Final state is saved to DB (`Submission` and all `Iteration` records).
    - Event `complete` is sent via SSE, closing the connection.

---

## 3. Data Infrastructure (Models & Schemas)

### Entity-Relationship Model
- **`Submission`**: Root record tracking global state (`pending`, `running`, `success`, `failed`), metadata (case_id, category), and final output.
- **`Iteration`**: Linked 1:N to Submission. Stores every snapshot: code, error logs, AI prompt, AI response, patch applied, and test results.

### Key Fields Detail
| Field | Role |
| :--- | :--- |
| `boost_context` | JSON snapshot of DB schema and Laravel docs used for *that* iteration. |
| `ai_prompt` | The exact prompt sent to the LLM (useful for debugging prompt drift). |
| `patch_applied` | Stringified `PatchSpec` (Action + Target + Replacement). |
| `mutation_score` | Rational percentage (0.0-100.0) from Pest mutation testing. |

---

## 4. Service Architecture Deep-Dive

### A. `DockerService` (The Sandbox)
Managed via the Docker SDK with strict security constraints:
- **Isolation**: `--network=none`, `--security-opt="no-new-privileges:true"`.
- **Resource Limits**: 512MB RAM, 0.5 CPU cores, 64 PID limit.
- **Commands**:
    - `copy_code()`: Uses a `tar` stream to write code directly to the container's memory-mapped filesystem, bypassing host temp files.
    - `execute()`: Runs commands inside the container using `asyncio.run_in_executor` to avoid blocking the main server thread.

### B. `BoostService` (Context Engine)
Exposes the internal state of the Laravel application to the AI:
- **Schema Discovery**: Runs `php artisan boost:schema` inside the container to retrieve table definitions.
- **Documentation**: Runs `php artisan boost:docs` to find relevant Laravel version-specific snippets for the current error.
- **Caching**: Implements a SHA-256 process-level cache for identical errors to reduce Docker overhead.

### C. `AIService` (Orchestrator)
Handles the conversation with LLMs:
- **Fallback Routing**: Uses an aggressive `FALLBACK_CHAIN`. If a provider (e.g. Cerebras) hits rate limits or throws a 429, the orchestrator instantly fails over to the next provider (e.g. Groq) without hanging the backend.
- **Prompt Templating**: Uses `api/prompts/repair_prompt.txt`. Avoids f-strings to prevent collision with PHP curly braces.
- **JSON Recovery**: Includes a robust custom parser `_fix_json_escapes` to strictly repair PHP namespace backslashes without corrupting LLM outputs (crucial for models like Deepseek-R1).
- **Retry Logic**: Tuned `tenacity` max wait to 10 seconds to fail-fast on API errors instead of sleeping for 15 minutes.

### D. `PatchService` (Mutation)
Applies the AI's suggested fixes to the current code version:
- **`replace`**: Exact string matching and replacement.
- **`append`**: Useful for adding missing imports or methods.
- **`create_file`**: Signals the loop to add a new physical file (e.g., a missing Model) to the next container's environment.

---

## 5. The Iterative Loop Logic (V2)

The `repair_service.py` runs a finite state machine that iterates up to **Max Iterations** (default 4):

**Pre-computation**: Spawns a persistent `laravel-sandbox` container. The container is lifted *out* of the iteration loop, solving the amnesia problem.

1.  **Code Injection**: Injects the current code version. Any supplementary models/files created in past iterations are naturally preserved in the container.
3.  **Validation (Lint & Tinker)**:
    - Runs `php -l` for syntax.
    - Uses `php artisan tinker` to verify the class is autoloadable via Laravel's service provider.
4.  **Error Diagnosis (The "Boost" Phase)**:
    - If code fails, the `BoostService` queries the container's internal Artisan for DB schema and docs.
5.  **LLM Inference**:
    - Sends the code + error + boost context to the LLM.
    - Returns a diagnosis, a `PatchSpec`, and a Pest test.
6.  **Pest Verification**: 
    - Executes the generated Pest test suite.
    - Runs the **Mutation Testing Gate** (`pest --mutate`).
7.  **Finalization/Repeat**: 
    - If Pest + Mutation Gate (>= 80%) pass -> Success.
    - Else -> Apply patch and start next iteration.

### Key Logic Nuances:
- **Sandbox Persistence**: Creating a model class on Iteration 1 means that file still physically exists on the filesystem in Iteration 2. This prevents the LLM from getting caught in amnesia loops.
- **Boilerplate Override**: If a `create_file` action results in a 0% mutation score (common for empty models), the system treats it as a success to prevent infinite loops on boilerplate.
- **Namespace Detection**: Uses `grep` to dynamically determine where in the `/app` tree the code should be placed (PSR-4 compliant).

---

## 6. API Endpoint Specification

### `POST /api/repair`
- **Security**: Requires Header `Authorization: Bearer <MASTER_TOKEN>`
- **Accepts**: `RepairRequest` (Code + iteration limits).
- **Returns**: `202 Accepted` + `submission_id`.

### `GET /api/repair/{id}/stream`
- **Mechanism**: Server-Sent Events (SSE).
- **Events**: `iteration_start`, `log_line`, `boost_queried`, `ai_thinking`, `pest_result`, `mutation_result`, `patch_applied`, `complete`.
- **FE Sync**: Due to fail-fast provider fallbacks, expect `log_line` events indicating `🔄 AI Provider failed. Retrying...`. FE clients should NOT close the connection upon seeing retries. 

### `GET /api/history`
- **Security**: Requires Header `Authorization: Bearer <MASTER_TOKEN>`
- Returns a paginated list of `SubmissionOut` objects.

### `POST /api/evaluate`
- **Security**: Requires Header `Authorization: Bearer <MASTER_TOKEN>`
- Triggers a batch evaluation using `api/routers/evaluate.py`. 

---

## 7. Configuration and Empirical Evaluation Framework

The platform supports robust Ablation Studies directly from `batch_manifest.yaml` utilizing test targets in `dataset/`:

1.  **Dataset Targets**: E.g. `case-001` containing a `code.php` file with a dedicated defective class.
2.  **Ablation Toggles**:
    - `use_boost_context`: Benchmarks repair success with/without framework-internal schematic injection.
    - `use_mutation_gate`: Benchmarks repair severity (forces survival against Pest's mutator engine).
3.  **Metrics Captured**:
    - **Success Rate** (Pass/Fail testing)
    - **Logic Evolution** (Number of iterations required)
    - **Recoil Resistance** (Mutation score generated)
4.  **Exports**: Test outputs are physically appended to `tests/integration/results/batch_report.csv` charting provider efficiencies.
