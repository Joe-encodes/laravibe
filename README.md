# AI-Enhanced Laravel Code Repair Platform
**Adamu Joseph Obinna — Thesis Project, March 2026**

---

## What This Is

A web platform that automatically repairs broken AI-generated PHP/Laravel REST API code using an **iterative loop**:

1. Paste broken Laravel code → click **Repair**
2. Code runs in an isolated Docker container; runtime errors are captured
3. **Laravel Boost** enriches the error with live schema + docs context
4. An LLM (Claude / GPT-4o) generates a minimal fix + Pest test
5. The fix is applied and re-run — repeating up to 7 times
6. A **mutation testing gate** (`pest --mutate ≥ 80%`) ensures the fix is robust
7. Watch everything stream live in the UI; download the repaired code

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Coordinator API | FastAPI (Python 3.12) |
| Container Runtime | Docker Engine 24.0+ |
| AI | Anthropic Claude (+ OpenAI fallback), `temperature=0.0` |
| Database | SQLite via SQLAlchemy + aiosqlite |
| PHP Runtime | PHP 8.3-alpine + Laravel 12 + Pest 3 + Laravel Boost |
| Frontend | Vanilla JS · CodeMirror 6 · diff2html |

---

## Quick Start

### 1. Prerequisites
- Docker Desktop running
- Python 3.12+
- A valid `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`

### 2. Setup
```bash
# Clone and enter the project
cd repair-platform

# Copy env template and fill in your API keys
cp .env.example .env

# Install Python deps
pip install -r requirements-dev.txt

# Build the Laravel sandbox image (takes ~5 minutes first time)
docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
```

### 3. Verify the image
```bash
docker run --rm laravel-sandbox:latest php -v
docker run --rm laravel-sandbox:latest php artisan --version
docker run --rm laravel-sandbox:latest ./vendor/bin/pest --version
docker run --rm laravel-sandbox:latest php artisan boost:status
```

### 4. Start the API
```bash
uvicorn api.main:app --reload --port 8000
```

### 5. Open the UI
Open `frontend/index.html` in your browser.

---

## Build Order (Batches)

Follow the **batch** order strictly. Never start Batch N until Batch N-1 passes **all** verification checks.

| Batch | Component | Status |
|-------|-----------|--------|
| 1 | Docker Sandbox Image | ✅ |
| 2 | FastAPI Skeleton + Database | ⬜ |
| 3 | Docker Service | ⬜ |
| 4 | AI Service | ⬜ |
| 5 | Boost Service | ⬜ |
| 6 | Patch Service | ⬜ |
| 7 | Repair Loop Service | ⬜ |
| 8 | API Routes + SSE Streaming | ⬜ |
| 9 | Mutation Testing Gate | ⬜ |
| 10 | Frontend | ⬜ |
| 11 | Integration Tests | ⬜ |
| 12 | MCP Server + CI | ⬜ |

---

## Security Rules (Non-Negotiable)

- Submitted code executes **only inside Docker** — never in Python
- Containers run with `--pids-limit=64 --memory=512m --network=none`
- API keys live in `.env` only — never baked into images
- Every container is destroyed in a `finally` block — no leaks

---

## MCP Integration (Batch 12)

After Batch 12, you can use this platform directly from Cursor/Claude Code:

```json
// .cursor/mcp_servers.json
{
  "laravel-repair": {
    "command": "python",
    "args": ["mcp/server.py"],
    "env": { "REPAIR_API_URL": "http://localhost:8000" }
  }
}
```

---

*Full implementation plan: `master_implementation_plan.md`*
