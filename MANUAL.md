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
17. [Administrative Controls](#17-administrative-controls)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. What This Platform Does

The **Laravel AI Repair Platform** automatically fixes broken AI-generated PHP/Laravel REST API code using an iterative loop of:

- **Docker container execution** (safe, isolated)
- **Laravel Boost context enrichment** (live schema + docs)
- **LLM-powered repair** (Claude, Gemini, GPT, Groq, DeepSeek, Ollama)
- **Pest test generation** (validates the fix works)
- **Mutation testing gate** (`pest --mutate ≥ 80%` — ensures the fix is robust)

It repeats up to **4 times** (configurable via `MAX_ITERATIONS` env var) until the code is clean, or reports failure.

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
  ├─ sandbox.create_container()  → isolated container spawned
  ├─ docker.copy_code()         → code.php copied in via tar archive
  ├─ docker.execute()           → PHP lint → artisan tinker validation
  │
  ├─ [if error] boost_service.query_context()   → php artisan boost:schema/docs inside container
  ├─ [if error] ai_service.get_repair()         → LLM call (XML pipeline)
  ├─ [if error] patch_service.apply_all()       → patches applied to container
  │
  ├─ [if success] Pest test run
  ├─ [if pest OK] run_mutation_test()  (mutation gate)
  │
  └─ SSE events streamed back → Browser updates panels live
```

The browser connects to `GET /api/repair/{id}/stream` via `EventSource` (Server-Sent Events) and receives real-time JSON events as the loop runs.

---

## 3. The 13-Step Iterative Repair Loop

### Design Change: Single Persistent Container (V2)

The container is created **once before the loop** and destroyed in `finally`. It persists across all iterations — files created by `create_file` patches in iteration N are naturally present in iteration N+1. No re-injection needed.

### Step-by-Step Breakdown

Each iteration follows this exact sequence in `api/services/repair/orchestrator.py`:

#### Step 1 — Bootstrap
`docker.copy_code()` writes to `/submitted/code.php`.

#### Step 2 — PHP Lint Gate
`php -l` check to fail fast on syntax errors.

#### Step 3 — Detect Class Info
`laravel.detect_class_info()` parses namespace and classname.

#### Step 4 — Place Code in Laravel
`laravel.place_code_in_laravel()` copies to PSR-4 path and runs `composer dump-autoload`.

#### Step 5 — Scaffold Route
`laravel.scaffold_route()` registers the API resource.

#### Step 6 — Zoom-In Discovery
`discovery.py` scans method signatures via reflection.

#### Step 7 — Query Boost Context
`boost_service.query_context()` fetches schema and docs.

#### Step 8 — Memory Recall
`context_service.retrieve_similar_repairs()` fetches RAG context.

#### Step 9 — Post-Mortem Analysis
`ai_service.get_post_mortem()` (non-fatal) analyzes previous failures.

#### Step 10 — Planner Strategy
The AI designs the fix and chooses which files to create or replace.

#### Step 11 — Executor & Patching
`patch_service.apply_all()` applies XML patches and creates new dependency files.

#### Step 12 — Functional Gate
`run_pest_test()` runs the baseline HTTP assertions.

#### Step 13 — Quality Gate
`run_mutation_test()` ensures the repair is robust.

#### Iteration Result
Each iteration saved as an `Iteration` row (including partial `mutation_score` even on fails). SSE `complete` event emitted on success or exhaustion.

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
│   ├── logging_config.py            ← Unified console + rotating file handler (10 MB × 5 backups)
│   ├── limiter.py                  ← slowapi rate limiter instance
│   ├── prompts/
│   │   └── repair_prompt.md        ← Main LLM repair prompt template (Spatie guidelines included)
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py               ← GET /api/health
│   │   ├── repair.py               ← POST /api/repair, GET /api/repair/{id}, SSE stream
│   │   ├── history.py              ← GET /api/history
│   │   ├── evaluate.py             ← POST /api/evaluate (batch runs)
│   │   ├── stats.py                ← GET /api/stats (aggregate statistics)
│   │   └── admin.py                ← DELETE /api/admin/submissions/{id}
│   │
│   ├── services/
│   │   ├── repair/                 ← Orchestration (orchestrator, pipeline, context)
│   │   ├── sandbox/                ← Container/Laravel logic (manager, docker, testing, laravel)
│   │   ├── ai_service.py           ← Multi-provider dispatcher & XML parser
│   │   ├── patch_service.py        ← Patch application & security blocklist
│   │   ├── boost_service.py        ← Laravel Boost context enrichment
│   │   ├── context_service.py      ← RAG-lite sliding window memory
│   │   ├── escalation_service.py   ← Stuck-loop detection
│   │   └── evaluation_service.py   ← Batch evaluation orchestrator
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
MAX_ITERATIONS=4
```

> **Note:** `CONTAINER_TIMEOUT_SECONDS` governs general exec calls. The mutation test timeout is hardcoded at 120 s in `sandbox_service.py` and is not yet controlled by this setting.

### App Settings

```env
DATABASE_URL=sqlite+aiosqlite:///./data/repair.db
MAX_CODE_SIZE_KB=100
REPAIR_TOKEN=change-me-in-production
DEBUG=false
MUTATION_SCORE_THRESHOLD=80
```

> **`DEFAULT_AI_PROVIDER=fallback`** — uses `FALLBACK_CHAIN` for single submissions. During batch evaluation, `ROTATION_CHAIN` in `ai_service.py` overrides this entirely per iteration.

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
| Nvidia NIM | `nvidia` | `Qwen/Qwen2.5-Coder-32B-Instruct` |
| Dashscope (Alibaba) | `dashscope` | `deepseek-v3` |
| Groq | `groq` | `llama-3.3-70b-versatile` |
| Cerebras | `cerebras` | `llama-3.3-70b` |
| Google Gemini | `gemini` | `gemini-2.5-flash` |
| DeepSeek | `deepseek` | `deepseek-coder` |
| Ollama | `ollama` | `qwen2.5-coder:7b` |
| Anthropic | `anthropic` | `claude-sonnet-4-6` |
| OpenAI | `openai` | `gpt-4o` |

### Batch Evaluation: ROTATION_CHAIN

During batch runs, `ROTATION_CHAIN` overrides `DEFAULT_AI_PROVIDER` per iteration:

| Iteration | Provider | Model |
|---|---|---|
| 0 | nvidia | `Qwen/Qwen2.5-Coder-32B-Instruct` |
| 1 | dashscope | `deepseek-v3` |
| 2 | nvidia | `meta/llama-3.3-70b-instruct` |
| 3 | gemini | `gemini-2.5-flash` |

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

### `sandbox_service.py`

Extracted from `repair_service.py`. Each function does one thing inside the container:

| Function | Purpose |
|---|---|
| `detect_class_info()` | PHP one-liners parse namespace + classname; builds `ClassInfo` |
| `setup_sqlite()` | Switches sandbox to SQLite (required under `--network=none`) |
| `place_code_in_laravel()` | PSR-4 placement + Tinker validation + `CLASS_OK` sentinel |
| `scaffold_route()` | Idempotent `Route::apiResource()` append to `routes/api.php` |
| `generate_baseline_pest_test()` | System-controlled HTTP assertion (no AI involvement) |
| `run_pest_test()` | `pest --filter=RepairTest --no-coverage` |
| `capture_laravel_log()` | Last 40 lines of `storage/logs/laravel.log` on Pest failure |
| `lint_test_file()` | `php -l RepairTest.php` before mutation gate |
| `run_mutation_test()` | `pest --mutate`; classifies output into 4 categories |
| `parse_mutation_score()` | 6-pattern regex with ANSI stripping; returns 0.0 on no match |
| `ensure_covers_directive()` | Injects `covers()` + `use function Pest\Laravel\{...};` |

---

### `patch_service.py`

Two permitted patch actions:

```
full_replace → replaces entire file content with replacement
create_file  → signals loop to write new file; current_code unchanged
```

`replace` and `append` are **banned** — raise `PatchApplicationError` immediately.

Forbidden filenames (`routes/api.php`, `routes/web.php`, etc.) are blocked silently — logged and skipped, not raised.

`apply_all()` processes a list of `PatchSpec` objects and returns `ApplyAllResult(updated_code, created_files, actions_taken, skipped_forbidden)`.

---

### `escalation_service.py`

4-rule stuck-loop detector evaluated after every failed iteration:
1. **Repeated diagnoses** — fuzzy match ≥ 70% word overlap across last 2 attempts → forces different reasoning
2. **Consecutive patch failures** → forces `full_replace`
3. **`create_file` without fixing original** → demands `full_replace` of the original file
4. **Dependency Guard** — same `create_file` path used more than once → forbids re-creating it

---

### `context_service.py`

200-item `deque` sliding window. On success, `store_repair_summary()` persists a `RepairSummary` row and appends to the deque immediately. On each new repair, `retrieve_similar_repairs()` scores entries by `(similarity × 0.7 + efficiency × 0.3)` and injects top-3 as prompt addendum.

---

### `repair_service.py`

The orchestrator — 413 lines. Key design decisions:

**Single persistent container** — created once before the iteration loop, destroyed in `finally`. Files from `create_file` patches persist naturally across iterations.

**`_normalize_code()`** — strips CRLF and UTF-8 BOM from submitted code on first receipt.

**`_normalize_migration()`** — converts named-class migrations to anonymous class syntax to prevent `Cannot redeclare class` errors.

**`iter_mutation_score` tracking** — partial mutation score stored on every iteration (even fails) so the research dataset has full score distributions.

**Laravel log capture** — on Pest failure, last 40 lines of `laravel.log` appended to `error_text` to surface the real PHP exception.

**Mutation score acceptance override** — if previous action was `create_file` and mutation score is 0%, system accepts it as success (boilerplate files have no mutations to test).

---

## 12. Database Schema

SQLite database at `data/repair.db` (created automatically on first startup).

### `submissions` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `user_id` | String (nullable) | Optional — for multi-user deployments |
| `created_at` | DateTime (UTC) | Submission timestamp |
| `original_code` | Text | Raw broken code as submitted |
| `user_prompt` | Text (nullable) | Optional extra instructions from user |
| `status` | String(20) | `pending` → `running` → `success` / `failed` |
| `total_iterations` | Integer | How many iterations ran |
| `final_code` | Text (nullable) | Repaired code if status=success |
| `error_summary` | Text (nullable) | Human-readable failure reason |
| `case_id` | String (nullable) | Batch evaluation case identifier |
| `category` | String (nullable) | Error category (e.g. `missing_model`) |
| `experiment_id` | String (nullable) | Batch run identifier |

### `iterations` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `submission_id` | UUID FK | Foreign key → submissions |
| `iteration_num` | Integer | 0-indexed iteration number |
| `code_input` | Text | Code version at start of this iteration |
| `execution_output` | Text | Container stdout |
| `error_logs` | Text | Combined stderr + stdout + Laravel log tail |
| `boost_context` | Text | JSON from boost_service |
| `ai_prompt` | Text | Full prompt sent to LLM |
| `ai_response` | Text | Raw LLM response JSON |
| `ai_model_used` | String(100) | e.g. `"nvidia/Qwen/Qwen2.5-Coder-32B-Instruct"` |
| `patch_applied` | Text | Stringified list of `PatchSpec` objects |
| `pest_test_code` | Text | AI-generated Pest test code |
| `pest_test_result` | Text | Pest output |
| `mutation_score` | Float | Score% from pest --mutate (NULL if gate not reached) |
| `status` | String(20) | `failed` or `success` |
| `duration_ms` | Integer | Iteration wall time in ms |
| `created_at` | DateTime (UTC) | Iteration start time |

### `repair_summaries` Table

Populated only on successful repairs. Feeds the sliding window memory.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `error_type` | String(255) | Extracted error signature (canonical key) |
| `diagnosis` | Text | What the AI diagnosed |
| `fix_applied` | Text | What fix was applied |
| `what_did_not_work` | Text (nullable) | Dead-end approaches from previous iterations |
| `iterations_needed` | Integer | How many iterations the repair took |
| `created_at` | DateTime (UTC) | When this repair was recorded |

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

## 17. Administrative Controls

The platform includes two critical production-grade controls for long-running repairs.

### 17.1 Administrative Kill Switch
If a repair is stuck or consuming excessive resources, you can terminate it from the dashboard.
- **Action**: Click the "🛑 Terminate" button on the active repair panel.
- **Backend**: Calls `DELETE /api/repair/{id}`.
- **Effect**: Hard-destroys the sandbox container and marks the submission as `cancelled`.

### 17.2 Forensic Playback (Historical Replay)
You can view the full live logs of any **completed** repair by navigating to its URL (e.g., `/repair/{id}`).
- **Mechanism**: The SSE stream automatically replays the `pipeline_logs` JSON stored in the database.
- **Observability**: Replays every event (`ai_thinking`, `pest_result`, etc.) exactly as it happened during the live run.

---

## 18. Troubleshooting

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

### Logs show `[Global]` instead of the submission ID

This is a known open issue. Only `repair_service.py` uses a `LoggerAdapter` with `submission_id`. All other services (`boost_service`, `docker_service`, `sandbox_service`, `patch_service`) use plain `logger.info()` which defaults to `"Global"` in the log format. You cannot currently filter the log file by a specific submission ID. Workaround: filter by the submission UUID string using `grep`:

```bash
grep "<your-submission-uuid>" data/logs/repair_platform.log
```

### Mutation score shows 0% with no explanation

The mutation score parser (`parse_mutation_score`) returns `0.0` silently when none of its 6 regex patterns match the Pest output. This is a known gap — no SSE event is emitted. Check the raw `ai_response` in the DB or the log file for the full Pest output to diagnose.

---

*Built for BSc Thesis — Adamu Joseph Obinna, 2026*
