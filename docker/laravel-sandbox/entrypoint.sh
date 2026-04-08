#!/bin/bash
# entrypoint.sh — Laravel Sandbox Container Startup Script
# Minimal: just configures .env and passes control to CMD / args.
# Heavy setup (migrations, boost) is done via docker exec from the Python service.

SANDBOX_DIR="/var/www/sandbox"
cd "$SANDBOX_DIR"

# ── Configure .env from environment variables (best-effort) ───────────────────
if [ -f .env.example ] && [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || true
fi

# Generate app key if not already set (best-effort)
php artisan key:generate --quiet 2>/dev/null || true
php artisan config:clear --quiet 2>/dev/null || true

# Warm Laravel config cache (boost.php is already published — no boost:cache command exists in Boost 2.3)
php artisan config:cache --quiet 2>/dev/null || true

# ── Execute any command passed as args (e.g. "sleep infinity") ────────────────
if [ $# -gt 0 ]; then
    exec "$@"
fi

# Fallback: keep container alive for exec
exec sleep infinity
