# Laravel AI Repair Platform — Comprehensive Technical Manual

**Author:** Adamu Joseph Obinna
**Version:** 1.0 — BSc Thesis 2026
**Stack:** FastAPI · Python 3.12 · Docker · Laravel 12 · Pest 3 · Laravel Boost · SQLite · Vanilla JS

---

## Table of Contents

1. [What This Platform Does](#1-what-this-platform-does)
2. [System Architecture](#2-system-architecture)
3. [The 7-Step Iterative Repair Loop](#3-the-7-step-iterative-repair-loop)
4. [Directory Structure & File Reference](#4-directory-structure--file-reference)
5. [Setting Up & Running (WSL Ubuntu)](#5-setting-up--running-wsl-ubuntu)
6. [Environment Variables Reference](#6-environment-variables-reference)
7. [AI Provider Configuration](#7-ai-provider-configuration)
8. [API Reference](#8-api-reference)
9. [Frontend UI Walkthrough](#9-frontend-ui-walkthrough)
10. [Docker Sandbox Explained](#10-docker-sandbox-explained)
11. [Services Deep-Dive](#11-services-deep-dive)
12. [Database Schema](#12-database-schema)
13. [Testing Guide](#13-testing-guide)
14. [MCP Integration (Cursor / Claude Code)](#14-mcp-integration-cursor--claude-code)
15. [Security Model](#15-security-model)
16. [Thesis Batch Evaluation](#16-thesis-batch-evaluation)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. What This Platform Does

The **Laravel AI Repair Platform** automatically fixes broken AI-generated PHP/Laravel REST API code using an iterative loop of:

- **Docker container execution** (safe, isolated)
- **Laravel Boost context enrichment** (live schema + docs)
- **LLM-powered repair** (Claude, Gemini, GPT, Groq, DeepSeek, Ollama)
- **Pest test generation** (validates the fix works)
- **Mutation testing gate** (`pest --mutate ≥ 80%` — ensures the fix is robust)

It repeats up to **7 times** until the code is clean, or reports failure.

### Core Mechanic in One Diagram

![System Architecture](C:\Users\ESTHER\.gemini\antigravity\brain\42fcb583-c7f5-4f26-950b-54824fad965d\architecture_diagram_1775660355152.png)

---

## 2. System Architecture

The platform operates as a multi-tier web application orchestration engine:

| Tier | Technology | Location |
|------|-----------|----------|
| **Frontend** | React 19 + TypeScript + Tailwind 4 | `laravibe-fe/` |
| **Coordinator API** | FastAPI Python 3.12 (asyncio) | `api/` |
| **Sandbox Runtime** | Docker container (PHP 8.3 + Laravel 12) | `docker/laravel-sandbox/` |
| **AI Providers** | Claude / Gemini / GPT / Groq / DeepSeek / Ollama | External / Local |

### Data Flow

```
Browser
  │  POST /api/repair  (broken code)
  ▼
FastAPI (repair.py router)
  │  Creates Submission record in SQLite
  │  Starts background task
  ▼
repair_service.run_repair_loop()
  │
  ├─ docker_service.create_container()  → isolated container spawned
  ├─ docker_service.copy_code()         → code.php copied in via tar archive
  ├─ docker_service.execute()           → PHP lint → artisan tinker validation
  │
  ├─ [if error] boost_service.query_context()   → php artisan boost:schema/docs inside container
  ├─ [if error] ai_service.get_repair()         → LLM call with full prompt + context
  ├─ [if error] patch_service.apply()           → diff applied to code string
  │
  ├─ [if success] Pest test run
  ├─ [if pest OK] pest --mutate  (mutation gate)
  │
  └─ SSE events streamed back → Browser updates panels live
```

The browser connects to `GET /api/repair/{id}/stream` via `EventSource` (Server-Sent Events) and receives real-time JSON events as the loop runs.

---

## 3. The 7-Step Iterative Repair Loop

![Iterative Repair Loop](C:\Users\ESTHER\.gemini\antigravity\brain\42fcb583-c7f5-4f26-950b-54824fad965d\repair_loop_diagram_1775660337398.png)

### Step-by-Step Breakdown

Each iteration (up to 7) follows this exact sequence implemented in [`api/services/repair_service.py`](api/services/repair_service.py):

#### Step 1 — Spin Container
```python
container = await docker_service.create_container()
```
A fresh `laravel-sandbox:latest` Docker container is created with:
- `--network=none` (zero internet access)
- `--memory=512m`
- `--pids-limit=64`
- `--cpu=0.5`

#### Step 2 — Copy Code
```python
await docker_service.copy_code(container, current_code)
```
The submitted PHP code is written to `/submitted/code.php` inside the container using an in-memory tar archive (no temp files on host).

#### Step 2b — Re-inject Dependency Files
If a previous iteration created new files (e.g. a missing `Product.php` Model), they are re-injected into every new container. This prevents the same "class not found" error re-appearing on subsequent iterations.

#### Step 3 — Execute Code
Execution runs in three sub-steps:
1. **PHP lint**: `php -l /submitted/code.php` — fastest possible syntax check
2. **Namespace/class detection**: `grep` extracts the class name and namespace
3. **Laravel Tinker validation**: `php artisan tinker --execute="class_exists(...)"` — loads the class through Laravel's full autoloader to catch runtime resolution failures

Success is detected by the `CLASS_OK` string in the Tinker output.

#### Step 4 — Error Check & Pest
If execution succeeds:
- **Pest functional test** runs: `./vendor/bin/pest --filter=RepairTest`
- If Pest passes → **Mutation gate**: `./vendor/bin/pest --mutate --coverage-pcov`
- Mutation score is parsed by `_parse_mutation_score()` from the Pest output

#### Step 5 — Query Boost Context
```python
boost_ctx_json = await boost_service.query_context(container, error_text)
```
Two artisan commands run **inside the container**:
- `php artisan boost:schema --format=text` — current DB schema
- `php artisan boost:docs --query="<error_type>" --limit=3` — relevant Laravel docs

Results are cached in-process by a SHA-256 hash of `(laravel_version, error_text[:500])`.

#### Step 6 — Call AI
```python
ai_resp = await ai_service.get_repair(code, error, boost_context, iteration, previous_attempts)
```
The LLM receives the repair prompt (in [`api/prompts/repair_prompt.txt`](api/prompts/repair_prompt.txt)) which includes:
- The broken code
- Runtime error output
- Laravel Boost context (schema + docs)
- All previous repair attempts in this session

The AI responds with structured JSON:
```json
{
  "diagnosis": "App\\Models\\Product class does not exist",
  "fix_description": "Create the missing Product model with correct namespace",
  "patch": {
    "action": "create_file",
    "target": null,
    "replacement": "<?php\n\nnamespace App\\Models;\n...",
    "filename": "App/Models/Product.php"
  },
  "pest_test": "<?php\ntest('Product model exists', fn() => ...);"
}
```

The `get_repair()` function retries up to **3 times** on malformed JSON (with exponential backoff via `tenacity`).

#### Step 7 — Apply Patch
The `patch_service.apply()` handles three action types:

| Action | What Happens |
|--------|-------------|
| `replace` | Finds exact `target` string in code and swaps it with `replacement` |
| `append` | Appends `replacement` to end of current code |
| `create_file` | Signals `repair_service` to write a new file at `patch.filename` inside the container |

The updated `current_code` (or new file) flows into the next iteration.

#### Iteration Result
Each iteration result is saved as an `Iteration` row in SQLite and an SSE event is streamed to the frontend. The loop either exits with `status=success` or exhausts all iterations and exits with `status=failed`.

---

## 4. Directory Structure & File Reference

```
repair-platform/
│
├── api/                            ← FastAPI Python backend
│   ├── __init__.py
│   ├── main.py                     ← App entry point, lifespan, middleware
│   ├── config.py                   ← All settings via pydantic-settings (.env)
│   ├── database.py                 ← Async SQLAlchemy engine + get_db() dependency
│   ├── models.py                   ← ORM: Submission, Iteration tables
│   ├── schemas.py                  ← Pydantic v2 request/response models
│   │
│   ├── prompts/
│   │   ├── repair_prompt.txt       ← Main LLM repair prompt template
│   │   └── pest_prompt.txt         ← Pest test generation prompt
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py               ← GET /api/health
│   │   ├── repair.py               ← POST /api/repair, GET /api/repair/{id}, SSE stream
│   │   ├── history.py              ← GET /api/history
│   │   └── evaluate.py             ← POST /api/evaluate (batch runs)
│   │
│   └── services/
│       ├── __init__.py
│       ├── docker_service.py       ← Container lifecycle (create/copy/exec/destroy)
│       ├── boost_service.py        ← Laravel Boost artisan commands + caching
│       ├── ai_service.py           ← LLM routing (Gemini/Groq/Claude/GPT/DeepSeek/Ollama)
│       ├── patch_service.py        ← Patch application (replace/append/create_file)
│       └── repair_service.py       ← Main orchestration loop (the big one, 434 lines)
│
├── docker/
│   ├── .dockerignore
│   └── laravel-sandbox/
│       ├── Dockerfile              ← PHP 8.3-alpine + Laravel 12 + Pest 3 + Laravel Boost
│       ├── docker-compose.yml      ← Optional compose for running the full stack
│       ├── entrypoint.sh           ← Container startup script
│       └── php.ini                 ← PHP config for the sandbox
│
├── frontend/
│   ├── index.html                  ← Single-page app layout (3-panel + sidebar)
│   ├── style.css                   ← Dark theme, panel layout, animations
│   └── app.js                      ← CodeMirror 5, SSE handling, diff2html, API calls
│
├── mcp/
│   └── server.py                   ← MCP JSON-RPC server (stdio transport)
│
├── scripts/
│   ├── dump_last_log.py            ← Debug utility: print last iteration logs from DB
│   └── run_case.sh                 ← Run a single evaluation case from batch manifest
│
├── tests/
│   ├── conftest.py                 ← Shared pytest fixtures (mock containers, PHP code)
│   ├── test_ai_service.py          ← Unit tests for LLM JSON parsing + prompt building
│   ├── test_boost_service.py       ← Unit tests for Boost context fetching + caching
│   ├── test_patch_service.py       ← Unit tests for all three patch actions
│   ├── test_repair_service.py      ← Unit tests for the repair loop state machine
│   ├── fixtures/
│   │   ├── missing_model.php       ← Broken: references App\Models\Product (doesn't exist)
│   │   ├── wrong_namespace.php     ← Broken: controller namespace doesn't match file path
│   │   └── missing_import.php     ← Broken: uses Str:: without importing the facade
│   └── integration/
│       └── test_full_repair.py     ← End-to-end tests (requires Docker + API key)
│
├── data/                           ← SQLite database lives here (auto-created)
├── venv/                           ← Python virtual environment (gitignored)
├── .env                            ← Secret keys (gitignored)
├── .env.example                    ← Template for .env
├── .gitignore
├── batch_manifest.yaml             ← Thesis evaluation configuration
├── pytest.ini                      ← Pytest config (asyncio_mode=auto)
├── requirements.txt                ← Python dependencies
├── start.sh                        ← WSL one-shot setup + launch script
└── PROJECT_MANUAL.md               ← Architecture overview (shorter version)
```

---

## 5. Setting Up & Running (WSL Ubuntu)

All Python dependencies are installed in WSL Ubuntu. Follow these steps exactly.

### Prerequisites

| Requirement | Check Command | Notes |
|------------|--------------|-------|
| Python 3.12+ | `python3 --version` | Must be 3.12+ |
| pip | `pip3 --version` | Comes with Python |
| Docker Desktop | `docker --version` | Enable WSL2 integration in Docker Desktop settings |
| At least one AI API key | — | Gemini is free at aistudio.google.com |

### Quickstart (One Command)

```bash
# Open WSL terminal, navigate to project, run:
bash start.sh
```

The `start.sh` script handles everything:
1. Creates Python virtual environment (`venv/`)
2. Installs all Python dependencies from `requirements.txt`
3. Copies `.env.example` → `.env` if `.env` doesn't exist
4. Checks Docker daemon is reachable
5. Builds the `laravel-sandbox:latest` Docker image (first time: ~5 minutes)
6. Runs unit tests
7. Starts the FastAPI server on `http://localhost:8000`

### Manual Setup (Step by Step)

```bash
# 1. Clone and enter (WSL path format)
cd "/mnt/c/Users/ESTHER/Desktop/Joseph's Project/laravel-ai-proj/repair-platform"

# 2. Create + activate venv
python3 -m venv venv
source venv/bin/activate

# 3. Install deps
pip install -r requirements.txt

# 4. Copy env and fill in your AI key
cp .env.example .env
nano .env   # Set GEMINI_API_KEY or another provider

# 5. Build the Docker sandbox image (once, ~5 min)
docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/

# 6. Verify the image
docker run --rm laravel-sandbox:latest php -v
docker run --rm laravel-sandbox:latest php artisan --version
docker run --rm laravel-sandbox:latest ./vendor/bin/pest --version

# 7. Start the API
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 8. Open the UI
# Open frontend/index.html in your browser
# OR visit http://localhost:8000/docs for the Swagger UI
```

### Accessing from Windows Browser

Since the server binds to `0.0.0.0`, you can open the frontend directly in your Windows browser:

- Open `frontend/index.html` as a file (double-click)  
- API: `http://localhost:8000`  
- Swagger docs: `http://localhost:8000/docs`  
- Health check: `http://localhost:8000/api/health`

---

## 6. Environment Variables Reference

All settings live in `.env` and are loaded by `api/config.py` via `pydantic-settings`.

### AI Provider Keys

| Variable | Description | Get It |
|---------|-------------|--------|
| `GEMINI_API_KEY` | Google Gemini (recommended — free) | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `GROQ_API_KEY` | Groq — free tier, fast | [console.groq.com](https://console.groq.com) |
| `DEEPSEEK_API_KEY` | DeepSeek — near-free, best code model | [platform.deepseek.com](https://platform.deepseek.com) |
| `ANTHROPIC_API_KEY` | Anthropic Claude — paid | [console.anthropic.com](https://console.anthropic.com) |
| `OPENAI_API_KEY` | OpenAI GPT — paid | [platform.openai.com](https://platform.openai.com) |
| `OLLAMA_BASE_URL` | Ollama local — no key needed | Default: `http://localhost:11434` |

### Active Provider Selection

```env
DEFAULT_AI_PROVIDER=gemini      # gemini | groq | deepseek | ollama | anthropic | openai
AI_MODEL=gemini-2.5-flash       # model name for the chosen provider
AI_TEMPERATURE=0.0              # always 0.0 for deterministic output
```

### Docker Settings

```env
DOCKER_IMAGE_NAME=laravel-sandbox:latest
CONTAINER_MEMORY_LIMIT=512m
CONTAINER_CPU_LIMIT=0.5
CONTAINER_PID_LIMIT=64
CONTAINER_TIMEOUT_SECONDS=90
MAX_ITERATIONS=7
```

### App Settings

```env
DATABASE_URL=sqlite+aiosqlite:///./data/repair.db
MAX_CODE_SIZE_KB=100
SECRET_KEY=change-this-in-production
DEBUG=false
MUTATION_SCORE_THRESHOLD=80
```

> [!IMPORTANT]
> Never commit `.env` — it is in `.gitignore`. Only `.env.example` (with placeholder values) is tracked by git.

---

## 7. AI Provider Configuration

The platform supports 6 AI backends. Switch by changing `DEFAULT_AI_PROVIDER` in `.env`.

### Recommended: Gemini (Free)

```env
DEFAULT_AI_PROVIDER=gemini
GEMINI_API_KEY=AIza...
AI_MODEL=gemini-2.5-flash
```

Gemini uses Google's OpenAI-compatible endpoint at `generativelanguage.googleapis.com/v1beta/openai/`. No extra SDK needed — the `openai` Python package handles it.

### Fast & Free: Groq

```env
DEFAULT_AI_PROVIDER=groq
GROQ_API_KEY=gsk_...
AI_MODEL=llama-3.3-70b-versatile
```

Groq hits `api.groq.com/openai/v1` — also OpenAI-compatible.

### Best Code Quality: DeepSeek

```env
DEFAULT_AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
AI_MODEL=deepseek-coder
```

### Fully Offline: Ollama

```bash
# Install Ollama then pull a model
ollama pull qwen2.5-coder:7b
```

```env
DEFAULT_AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
AI_MODEL=qwen2.5-coder:7b
```

Ollama requires at least 8GB RAM. Useful for air-gapped environments.

### Model Routing Table

| Provider | `DEFAULT_AI_PROVIDER` | Recommended `AI_MODEL` |
|---------|----------------------|------------------------|
| Google Gemini | `gemini` | `gemini-2.5-flash` |
| Groq | `groq` | `llama-3.3-70b-versatile` |
| DeepSeek | `deepseek` | `deepseek-coder` |
| Ollama | `ollama` | `qwen2.5-coder:7b` |
| Anthropic | `anthropic` | `claude-sonnet-4-6` |
| OpenAI | `openai` | `gpt-4o` |

---

## 8. API Reference

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs`

### `GET /api/health`

Returns status of all connected services.

**Response:**
```json
{
  "status": "ok",
  "docker": "connected",
  "ai": "key_set",
  "db": "connected"
}
```

---

### `POST /api/repair`

Submit broken PHP/Laravel code for repair.

**Request body:**
```json
{
  "code": "<?php\nnamespace App\\Http\\Controllers\\Api;\n...",
  "max_iterations": 7
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `code` | string | ✅ | Must not be empty. Max `MAX_CODE_SIZE_KB` KB |
| `max_iterations` | int | ❌ | 1–10, defaults to `MAX_ITERATIONS` env var |

**Response (202 Accepted):**
```json
{
  "submission_id": "3a1b2c4d-...",
  "status": "pending",
  "message": "Repair queued. Connect to the stream endpoint for live progress."
}
```

Repair runs as a **background task** — the 202 response is immediate.

---

### `GET /api/repair/{submission_id}/stream`

Server-Sent Events (SSE) stream. Connect with `EventSource` in JS.

Each event is a JSON object:
```
data: {"event": "log_line", "data": {"msg": "Spinning up sandbox container..."}}

data: {"event": "iteration_start", "data": {"iteration": 1, "max": 7}}

data: {"event": "boost_queried", "data": {"schema": true, "component_type": "model"}}

data: {"event": "ai_thinking", "data": {"diagnosis": "...", "fix_description": "..."}}

data: {"event": "pest_result", "data": {"status": "pass", "output": "..."}}

data: {"event": "mutation_result", "data": {"score": 85.0, "threshold": 80, "passed": true}}

data: {"event": "patch_applied", "data": {"action": "replace", "fix": "Added missing import"}}

data: {"event": "complete", "data": {"status": "success", "final_code": "...", "iterations": 2, "mutation_score": 85.0}}
```

### SSE Event Reference

| Event | Emitted When |
|-------|-------------|
| `iteration_start` | Each loop iteration begins |
| `log_line` | Info/status message |
| `boost_queried` | Laravel Boost context retrieved |
| `ai_thinking` | LLM has returned a diagnosis and fix |
| `pest_result` | Pest tests have run |
| `mutation_result` | Mutation testing gate result |
| `patch_applied` | A patch was successfully applied |
| `error` | Non-fatal error (loop continues if possible) |
| `complete` | Loop finished (success or failed) |

---

### `GET /api/repair/{submission_id}`

Get the full result including all iteration details.

**Response:**
```json
{
  "id": "3a1b2c4d-...",
  "status": "success",
  "created_at": "2026-04-08T14:00:00Z",
  "total_iterations": 2,
  "final_code": "<?php\n...",
  "error_summary": null,
  "iterations": [
    {
      "id": "...",
      "iteration_num": 0,
      "status": "failed",
      "error_logs": "Fatal error: Class not found...",
      "patch_applied": "...",
      "pest_test_result": null,
      "mutation_score": null,
      "duration_ms": 4200,
      "created_at": "..."
    }
  ]
}
```

---

### `GET /api/history`

Returns the 50 most recent submissions (without iteration details).

---

### `POST /api/evaluate`

Runs the full batch evaluation suite defined in `batch_manifest.yaml`. Used for thesis experiments.

---

## 9. Frontend Deep-Dive (`laravibe-fe/`)

The frontend is a modern SPA designed for real-time observability and high-density data visualization, moving far beyond traditional static HTML to a dynamic URL-driven shell.

### 9.1 Technology Stack
- **Framework**: React 19 with TypeScript.
- **Build Tool**: Vite 6.
- **Styling**: Tailwind CSS 4.0 with `@tailwindcss/vite` plugin.
- **Routing**: React Router 7 (URL-driven navigation ensures deep-linked history mapping perfectly to `Submission` UUIDs).
- **Icons & Components**: Lucide React icons, framer-motion (optional micro-animations).

### 9.2 Design System: "Glass-Industrial"
The platform features an Anthropic-inspired aesthetic intended for professional research environments:
- **Surface Layering**: Hierarchical transparency (`surface-container-low/high/lowest`) simulating depth without relying on heavy shadows.
- **Typography**: Extensive use of monospaced and modern sans-serif fonts for code-centric observability.
- **Interaction HUD**: Hover-triggered accents and pulsing status indicators for the repair loop.

### 9.3 Live Streaming Engine (SSE)
The `RepairView` component utilizes an `EventSource` to visualize the backend workflow. The frontend state engine maps incoming backend SSE events to a linear UI progression:
`SPINNING` → `BOOSTING` → `THINKING` → `PATCHING` → `TESTING` → `MUTATING` → `COMPLETE`.

It gracefully parses `data: {"event": "log_line", ...}` updates, appending them to a virtualized log scroller.

---

## 10. DevOps & Sandbox Orchestration

The platform employs a strictly isolated runtime model to ensure security and execution determinism.

### 10.1 Sandbox Build Architecture (`laravel-sandbox:latest`)
Built from `docker/laravel-sandbox/Dockerfile`, the image outputs a production-grade Alpine 3.20 + PHP 8.3 environment preloaded with Laravel 12 and Pest 3. 

The build pipeline:
1. Installs Alpine system packages.
2. Compiles Redis and `pcov` (for mutation testing coverage) via parallelized `pecl`.
3. Bootstraps `composer create-project laravel/laravel sandbox "12.*"`.
4. Installs Laravel Pest, Boost, and Sanctum packages.

### 10.2 Automated Environment Setup (`start.sh`)
The `start.sh` utility orchestrates the entire DevOps lifecycle for local development:
1. **Venv Management**: Automates Python 3.12 environment creation and package synchronization.
2. **Secret Management**: Validates `.env` and `SECRET_KEY` presence.
3. **Image Logic**: Checks for `laravel-sandbox:latest` and performs a clean build if missing.
4. **Daemon Assessment**: Validates the Docker daemon is accessible via WSL2 integration.

### 10.3 Container Security Constraints
Each code execution runs within a tightly bounded lifecycle:

```python
client.containers.run(
    image="laravel-sandbox:latest",
    network_mode="none",                    # Zero internet access
    mem_limit="512m",                       # Memory cap restricts OOM payloads
    nano_cpus=int(0.5 * 1e9),              # 0.5 CPU core restricts cryptomining/CPU hogs
    pids_limit=64,                          # Max 64 processes restricts fork bombs
    security_opt=["no-new-privileges:true"],
    command="sleep infinity",               # Stays alive for exec commands
)
```

**Critically:** every container is forcefully destroyed inside a `finally` block in `repair_service.py`. No container leaks or persists beyond an iteration crash.

### 10.4 Code Injection Mechanism
User code is streamed to `/submitted/code.php` inside the container via Python's `tarfile` module — utilizing an in-memory tar-streaming mechanism without touching the host filesystem.

The repair pipeline then:
1. Detects the PHP namespace.
2. Copies `code.php` to the correct location in the Laravel directory tree.
3. Automatically triggers `composer dump-autoload` to register the class.
4. Validates class-loading logic via `php artisan tinker`.

---

## 11. Services Deep-Dive

### `docker_service.py`

| Function | Purpose |
|----------|---------|
| `create_container()` | Spin up fresh container with security limits |
| `copy_code(container, code)` | Write PHP to `/submitted/code.php` via tar |
| `execute(container, command, timeout, user)` | Run shell command, return `ExecResult(stdout, stderr, exit_code, duration_ms)` |
| `destroy(container)` | Stop + remove container (always in `finally`) |
| `health_check()` | Ping Docker daemon |

`ExecResult.has_php_fatal` checks for PHP fatal errors that don't produce non-zero exit codes (PHP's inconsistent error handling).

All blocking Docker SDK calls run in `asyncio.run_in_executor()` to avoid blocking the async event loop.

---

### `boost_service.py`

**Laravel Boost** is a development package that exposes `artisan boost:schema` and `artisan boost:docs` commands to retrieve the current application's DB schema and relevant Laravel documentation.

The service runs these commands **inside the sandbox container** so it sees the exact Laravel project state, then returns the context as JSON for the AI prompt.

**Caching:** Results are stored in an in-process dict keyed by `SHA-256(laravel_version + error_text[:500])`. Identical errors within a session skip the Docker exec entirely.

---

### `ai_service.py`

The AI service:
1. Builds the prompt from `repair_prompt.txt` template using `.replace()` (not f-strings — safer with PHP code containing curly braces)
2. Routes to the configured provider via a dispatch dict
3. Parses the JSON response — including fixing common escape issues where PHP namespaces (`App\Models\Product`) break JSON without double-escaping
4. Retries up to 3× on `ValueError` / `JSONDecodeError` via `tenacity`

**The repair prompt template** explicitly instructs the LLM to:
- Return **only** valid JSON — no prose, no markdown
- Fix **only** what is broken (minimal patch)
- Use one of three patch actions: `replace`, `append`, `create_file`
- Produce a deterministic Pest test (no network calls, no time-dependent logic)

---

### `patch_service.py`

Three patch actions:

```
replace     → current_code.replace(patch.target, patch.replacement, 1)
append      → current_code + "\n\n" + patch.replacement
create_file → signal to repair_service; new file written to container
```

All AI responses have markdown fences stripped via `strip_markdown_fences()` before applying — models often wrap code in ` ```php ` even when instructed not to.

---

### `repair_service.py`

The orchestrator — 434 lines. Key design decisions:

**`supplementary_files` dict** tracks files created by `create_file` patches. Since each iteration uses a fresh container, any new files from iteration N would be lost in iteration N+1. The dict re-injects them with `cat << 'EOF'` heredoc commands.

**Mutation score acceptance override:** If the previous repair action was `create_file` (e.g. created a new empty Model) and mutation score is 0%, the system accepts it as genuine success. Empty boilerplate files have no mutations to test — treating 0% as failure would cause infinite loops.

---

## 12. Database Schema

SQLite database at `data/repair.db` (created automatically on first startup).

### `submissions` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `created_at` | DateTime (UTC) | Submission timestamp |
| `original_code` | Text | Raw broken code as submitted |
| `status` | String(20) | `pending` → `running` → `success` / `failed` |
| `total_iterations` | Integer | How many iterations ran |
| `final_code` | Text (nullable) | Repaired code if status=success |
| `error_summary` | Text (nullable) | Human-readable failure reason |

### `iterations` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `submission_id` | UUID FK | Foreign key → submissions |
| `iteration_num` | Integer | 0-indexed iteration number |
| `code_input` | Text | Code version at start of this iteration |
| `execution_output` | Text | Container stdout |
| `error_logs` | Text | Combined stderr + stdout from failed exec |
| `boost_context` | Text | JSON from boost_service |
| `ai_prompt` | Text | Full prompt sent to LLM |
| `ai_response` | Text | Raw LLM response JSON |
| `patch_applied` | Text | String repr of PatchSpec |
| `pest_test_code` | Text | Pest test code from AI |
| `pest_test_result` | Text | Pest output |
| `mutation_score` | Float | Score% from pest --mutate |
| `status` | String(20) | `failed` or `success` |
| `duration_ms` | Integer | Iteration wall time in milliseconds |
| `created_at` | DateTime (UTC) | Iteration start time |

---

## 13. Testing Guide

Tests live in `tests/`. All unit tests use mocks — **no real Docker or AI calls needed**.

### Run Unit Tests

```bash
source venv/bin/activate

# All unit tests (fast, no Docker needed)
pytest tests/ -m "not integration" -v

# Specific service
pytest tests/test_repair_service.py -v
pytest tests/test_ai_service.py -v
pytest tests/test_patch_service.py -v
pytest tests/test_boost_service.py -v
```

### Run Integration Tests

Integration tests require Docker and a real AI API key:

```bash
# Ensure Docker is running and .env has a valid AI key
pytest tests/integration/ -v --timeout=120
```

### Unit Test Coverage

| Test File | What It Tests |
|-----------|--------------|
| `test_repair_service.py` | Repair loop: success path, exhausted iterations, weak mutation score |
| `test_ai_service.py` | JSON parsing, prompt building, JSON escape repair |
| `test_boost_service.py` | Context fetching, caching, component type detection |
| `test_patch_service.py` | All three patch actions, error on missing target |

### Key Test Patterns

Tests mock the entire Docker layer using `unittest.mock.AsyncMock`:

```python
with (
    patch("api.services.repair_service.docker_service.create_container", AsyncMock(return_value=MagicMock())),
    patch("api.services.repair_service.docker_service.execute",
          AsyncMock(side_effect=[lint_ok, ns_ok, cls_ok, tinker_ok, pest_ok, mut_ok])),
    ...
):
    events = await _collect(run_repair_loop(...))
```

Events are collected from the async generator and asserted against — `status=success`, `mutation_score >= 80`, etc.

### `pytest.ini` Configuration

```ini
[pytest]
asyncio_mode = auto
markers =
    integration: marks tests as integration tests (require Docker+API key, slow)
```

`asyncio_mode=auto` means all `async def test_...` functions run automatically without needing `@pytest.mark.asyncio`.

---

## 14. MCP Integration (Cursor / Claude Code)

The platform exposes itself as an **MCP (Model Context Protocol)** tool server, allowing AI coding assistants like Cursor or Claude Code to call it directly.

### Cursor Setup

Create `.cursor/mcp.json` in your project:

```json
{
  "laravel-repair": {
    "command": "python",
    "args": ["mcp/server.py"],
    "env": {
      "REPAIR_API_URL": "http://localhost:8000"
    }
  }
}
```

### Available MCP Tool

**`repairLaravelApiCode`**

Parameters:
- `code` (string, required): Broken PHP/Laravel REST API code
- `max_iterations` (integer, optional, 1–10): Default 7

Returns:
```json
{
  "status": "success",
  "submission_id": "...",
  "iterations": 2,
  "repaired_code": "<?php\n...",
  "diagnosis": "App\\Models\\Product class did not exist",
  "mutation_score": 87.5
}
```

### Protocol

The MCP server uses **JSON-RPC 2.0 over stdio** transport — standard for MCP. It:
1. Receives `tools/list` requests and describes the available tool
2. Receives `tools/call` requests, submits code to the FastAPI backend, and polls until done
3. Streams the final result back as a JSON text block

The server polls every 1.5 seconds with a 10-minute timeout.

---

## 15. Security Model

### Threat: Code Injection

**Risk:** Submitted PHP code could be malicious (delete files, spawn processes, make network calls).

**Mitigation:** Code runs **exclusively inside Docker**. The Python application never executes PHP code directly. Every container has:
- `--network=none` — zero internet access
- `--memory=512m` — prevents OOM attacks
- `--pids-limit=64` — prevents fork bombs
- `--security-opt=no-new-privileges:true` — prevents privilege escalation

### Threat: Container Leaks

**Risk:** A crashed iteration could leave containers running, consuming resources.

**Mitigation:** Every `create_container()` call is paired with `destroy()` inside a `finally` block:

```python
container = None
try:
    container = await docker_service.create_container()
    ...
except Exception:
    ...
finally:
    if container:
        await docker_service.destroy(container)  # Always runs
```

### Threat: API Key Exposure

**Risk:** Committing `.env` to git exposes API keys.

**Mitigation:** `.env` is in `.gitignore`. Only `.env.example` (with placeholder values) is committed. Settings are loaded exclusively through `api/config.py` — never read directly from `os.environ` elsewhere.

### Threat: Oversized Code Submission

**Risk:** Submitting a 100MB PHP file causes memory/timeout issues.

**Mitigation:** `POST /api/repair` validates code size against `MAX_CODE_SIZE_KB` (default 100KB) and returns HTTP 400 if exceeded.

---

## 16. Thesis Batch Evaluation

`batch_manifest.yaml` defines all parameters for the thesis experiments.

```yaml
project_name: laravel-ai-repair
ai_provider: anthropic
ai_model: claude-sonnet-4-6
ai_temperature: 0.0          # Deterministic — critical for thesis reproducibility
max_iterations: 7
mutation_score_threshold: 80
batch_size: 10

resource_limits:
  cpus: "0.5"
  memory: 512m
  pids: 64
  timeout_s: 90

# Ablation flags — run without one to measure its contribution
use_boost_context: true      # Set false to test without Laravel Boost
use_mutation_gate: true      # Set false to test without mutation validation

cases:
  - id: case-001
    type: missing_model        # Class referenced but never created
  - id: case-002
    type: wrong_namespace      # Namespace doesn't match file path
  - id: case-003
    type: missing_import       # Facade used without importing
```

### Running a Batch

```bash
# Run single evaluation case
bash scripts/run_case.sh case-001

# Run full batch via API
curl -X POST http://localhost:8000/api/evaluate
```

Results are written to `tests/integration/results/batch_report.csv`.

### Ablation Study Design

The manifest supports two ablation flags:
- `use_boost_context: false` — disables Laravel Boost context enrichment (measures Boost's contribution)
- `use_mutation_gate: false` — disables the 80% mutation threshold (measures mutation gate's contribution)

---

## 17. Troubleshooting

### `laravel-sandbox:latest` image not found

```
docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
```

Allow 5 minutes on first run.

### `Docker daemon unreachable`

- Open Docker Desktop on Windows
- Go to Settings → Resources → WSL Integration
- Enable integration for your Ubuntu distro
- Restart Docker Desktop

### `APIStatusError: 401` or `AuthenticationError`

Your API key is incorrect or not set in `.env`. Check:
```bash
grep API_KEY .env
```

### Mutation tests report 0% but code is correct

This happens when the submitted file has no logic to mutate (e.g. a pure boilerplate Model file). The system automatically accepts `0%` as success if the previous patch action was `create_file`.

### `PatchApplicationError: Patch target not found`

The LLM returned a `replace` patch with a `target` string that doesn't exist in the current code. This is typically caused by:
- The model returning slightly reformatted code as the target
- The code having been modified in a previous iteration

The loop continues and the AI receives the error on its next attempt.

### Database issues

Delete `data/repair.db` to start fresh — the tables are recreated automatically on next startup.

### Dump last iteration logs

```bash
python3 scripts/dump_last_log.py
```

---

*Built for BSc Thesis — Adamu Joseph Obinna, 2026*
