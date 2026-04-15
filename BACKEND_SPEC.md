# LaraVibe Backend: Technical Architecture & Logic Deep-Dive

This document provides a low-level technical specification of the LaraVibe (Laravel AI Repair Platform) backend. It focuses exclusively on the FastAPI coordinator, its service layer, and the iterative repair mechanics.

---

## 1. Core Technology Stack

- **Framework**: [FastAPI 0.115+](https://fastapi.tiangolo.com/) (Python 3.12)
- **Asynchronous Engine**: `asyncio` for non-blocking I/O (Docker exec, AI calls, DB).
- **ORM**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with `aiosqlite` (Async SQLite).
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/latest/) for request/response schemas and environment settings.
- **Orchestration**: [Docker Python SDK](https://docker-py.readthedocs.io/) for sandbox lifecycle management.
- **AI Integration**: OpenAI-compatible client (supporting Gemini, Groq, DeepSeek, Anthropic, OpenAI).
- **Reliability**: `tenacity` for exponential backoff retries on LLM parsing failures.

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
- **Prompt Templating**: Uses `api/prompts/repair_prompt.txt`. Avoids f-strings to prevent collision with PHP curly braces.
- **JSON Recovery**: Includes a robust custom parser to handle common LLM mistakes (markdown fences, unescaped PHP backslashes).
- **Retry Logic**: 3-tier retry on malformed JSON or provider timeout using `tenacity`.

### D. `PatchService` (Mutation)
Applies the AI's suggested fixes to the current code version:
- **`replace`**: Exact string matching and replacement.
- **`append`**: Useful for adding missing imports or methods.
- **`create_file`**: Signals the loop to add a new physical file (e.g., a missing Model) to the next container's environment.

---

## 5. The 7-Step Iterative Loop Logic

The `repair_service.py` runs a finite state machine that iterates up to **7 times** (configurable):

1.  **Start Iteration**: Spawns a fresh `laravel-sandbox` container.
2.  **Code Injection**: Injects the current code version + any supplementary models/files created in past iterations.
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
- **Supplementary Files**: Files created via `create_file` are stored in a `supplementary_files` dict and re-injected into every fresh container.
- **Boilerplate Override**: If a `create_file` action results in a 0% mutation score (common for empty models), the system treats it as a success to prevent infinite loops on boilerplate.
- **Namespace Detection**: Uses `grep` to dynamically determine where in the `/app` tree the code should be placed (PSR-4 compliant).

---

## 6. API Endpoint Specification

### `POST /api/repair`
- **Accepts**: `RepairRequest` (Code + iteration limits).
- **Returns**: `202 Accepted` + `submission_id`.
- **Inner Workings**: Validates code presence, creates DB entry, starts async background task.

### `GET /api/repair/{id}/stream`
- **Mechanism**: Server-Sent Events (SSE).
- **Events**: `iteration_start`, `log_line`, `boost_queried`, `ai_thinking`, `pest_result`, `mutation_result`, `patch_applied`, `complete`.

### `GET /api/history`
- Returns a paginated list of `SubmissionOut` objects (history overview).

### `POST /api/evaluate`
- Triggers a batch evaluation suit using `api/routers/evaluate.py`. Loads `batch_manifest.yaml` and iterates over samples in `dataset/`, executing the full repair loop for each.
