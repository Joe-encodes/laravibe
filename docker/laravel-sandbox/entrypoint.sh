#!/bin/bash
# entrypoint.sh — Laravel Sandbox Container Startup Script
# Configures the Laravel .env for SQLite and warms caches.
# Heavy setup (migrations, code injection) is performed via docker exec from the Python service.

SANDBOX_DIR="/var/www/sandbox"
cd "$SANDBOX_DIR"

# ── 1. Bootstrap .env from example ────────────────────────────────────────────
if [ -f .env.example ] && [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || true
fi

# ── 2. Configure SQLite (no MySQL/Redis required in sandbox) ──────────────────
# The sandbox runs --network=none; no external services are reachable.
sed -i 's/^DB_CONNECTION=.*/DB_CONNECTION=sqlite/' .env
sed -i '/^DB_HOST=/d' .env
sed -i '/^DB_PORT=/d' .env
sed -i '/^DB_DATABASE=/d' .env
sed -i '/^DB_USERNAME=/d' .env
sed -i '/^DB_PASSWORD=/d' .env

# Ensure the SQLite database file exists
touch database/database.sqlite

# ── 3. Generate app key and cache config ──────────────────────────────────────
php artisan key:generate --quiet 2>/dev/null || true
php artisan config:clear --quiet 2>/dev/null || true
php artisan config:cache --quiet 2>/dev/null || true

# ── 4. Execute any command passed as args (e.g. "sleep infinity") ─────────────
if [ $# -gt 0 ]; then
    exec "$@"
fi

# Fallback: keep container alive for exec
exec sleep infinity
