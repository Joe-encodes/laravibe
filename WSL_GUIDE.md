# LaraVibe WSL & Backend Hardening Rules

This document outlines the strict guidelines for interacting with the LaraVibe Backend on WSL/Ubuntu. These rules ensure stability, prevent database locks, and maintain system integrity.

## 1. Environment & Commands
- **WSL Only**: All commands MUST be run inside the WSL/Ubuntu environment, never directly on Windows CMD/PowerShell.
- **Shell Scripts**: For complex operations, prefer creating `.sh` files and executing them with `bash`.
- **Python Venv**: Always use `./venv/bin/python3` or activate the venv before running scripts.

## 2. Server Management
- **One Source of Truth**: The server is started via `bash start.sh`.
- **Ownership**: Only restart/kill the server if you are applying critical code changes (e.g., in `api/services/ai_service.py` or `api/config.py`).
- **Health Check First**: Before running tests, always verify the server is healthy with:
  ```bash
  curl -s http://127.0.0.1:8000/api/health
  ```

## 3. SQLite & Database Integrity
- **Non-Blocking I/O**: SQLite is sensitive to shared locks. Never hold a database session open during long-running tasks (like AI calls).
- **Explicit Commits**: Call `await db.commit()` immediately after `SELECT` or `UPDATE` operations to release shared locks, especially in high-concurrency areas like the SSE stream or context loader.
- **Direct Inspection**: To inspect results without the API, use the `sqlite3` CLI:
  ```bash
  sqlite3 data/repair.db "SELECT * FROM iterations ORDER BY created_at DESC LIMIT 1;"
  ```
- **Concurrency**: Be aware that the SSE stream and the background repair worker share the same database. Lock contention is the #1 cause of crashes.

## 4. AI & Repair Logic
- **Dollar Sign Escaping**: Be vigilant about models escaping dollar signs (`\$var`). This platform uses a custom `_fix_json_escapes` function in `ai_service.py` to unescape these before parsing.
- **Pest 3 Directives**: Every test file MUST include the `covers()` directive and `uses(RefreshDatabase::class)`. The platform auto-injects these, but the AI should attempt to produce them correctly.
- **Escalation**: If a repair loop is stuck (creating the same files repeatedly), the system will automatically escalate the prompt to force a pivot.

## 5. Logging & Auditing
- **Contextual Logging**: All logs include a `[submission_id]` or `[Global]` prefix.
- **Real-time Tail**: Use `tail -f data/logs/repair_platform.log` to watch the repair process in real-time.
- **Audit Trail**: The `iterations` table in the database contains the full prompt and response history for every step. Use this for debugging hallucinations.
