# LaraVibe Backend: API & Architecture Map

This document maps the physical file structure to the logical API endpoints and repair lifecycle.

---

## 1. Directory Blueprint

| Path | Purpose |
|---|---|
| `api/main.py` | FastAPI entry point, lifespan, and global exception handlers |
| `api/routers/repair.py` | **The Core**: `POST /api/repair` (submission) and `GET /stream` (SSE) |
| `api/services/repair/` | **The Brain**: Orchestrates the Planner/Executor loop |
| `api/services/sandbox/` | **The Sandbox**: Manages Docker containers and Laravel interaction |
| `api/services/ai_service.py` | **The LLM Hub**: Handles provider pools, retries, and XML parsing |
| `api/services/patch_service.py` | **The Guard**: Applies code changes with security blocklists |

---

## 2. API Endpoint → Code Logic Map

### `POST /api/repair`
- **File**: `api/routers/repair.py:submit_repair`
- **Logic**:
  1. Validates code size.
  2. Creates DB entry (`Submission`).
  3. Hands off to `api.services.repair.run_repair_loop` via `BackgroundTasks`.

### `GET /api/repair/{id}/stream` (SSE)
- **File**: `api/routers/repair.py:stream_repair`
- **Logic**:
  - Consumes an in-memory `_event_queues` list.
  - Replays history automatically if a client reconnects.
  - Standardizes on named events (e.g., `event: log_line`).

---

## 3. The 13-Step Repair Lifecycle
The repair loop lives in `api/services/repair/orchestrator.py` and follows these exact steps:

1. **Bootstrap**: `copy_code` to sandbox.
2. **Detection**: `detect_class_info` (PSR-4 pathing).
3. **DB Prep**: `setup_sqlite` inside container.
4. **Placement**: `place_code_in_laravel`.
5. **Routing**: `scaffold_route` (API registration).
6. **Discovery**: `discovery.py` scans method signatures.
7. **Enrichment**: `boost_service` (schema + docs).
8. **Memory**: `context_service` (similar past repairs).
9. **Analysis**: `POST_MORTEM` check (non-fatal critic).
10. **Planning**: `Planner` role (Strategy + Diagnosis).
11. **Execution**: `Executor` role (XML Patch Generation).
12. **Functional Gate**: `run_pest_test` (Baseline).
13. **Quality Gate**: `run_mutation_test` (Mutation score ≥ 80%).

---

## 4. AI Provider Pools (Hardenened)
The system rotates through these pools in `ai_service.py` to handle 429 errors:

- **PLANNER/VERIFIER/REVIEWER**: `Groq → Cerebras → Dashscope → Nvidia`
- **EXECUTOR**: `Nvidia → Groq → Cerebras → Dashscope`
- **POST_MORTEM**: `Groq → Cerebras → Dashscope`

---

## 5. Security Model
- **Auth**: `Bearer <REPAIR_TOKEN>` required for all `/api/*` endpoints.
- **Path Guard**: `patch_service.py` blocks writes to `.env`, `artisan`, `composer.json`, etc.
- **Sandbox Isolation**: No network access (`none`), limited CPU (0.5), and limited RAM (512MB).
