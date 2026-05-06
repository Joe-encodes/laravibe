#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start_prod.sh — Production launch script for Laravel AI Repair Platform
# Optimized for cloud environments (Ubuntu/Koyeb)
# ─────────────────────────────────────────────────────────────────────────────
set -e

# 1. Environment Checks
export REPAIR_ENV="production"
PORT="${PORT:-8000}"

echo ">>> Starting LaraVibe in PRODUCTION mode on port $PORT"

# 2. Infrastructure Setup
# Ensure data and logs directories exist
mkdir -p data logs

# 3. Docker Sandbox Check
if docker info > /dev/null 2>&1; then
    echo ">>> Docker detected. Verifying sandbox image..."
    if ! docker image inspect laravel-sandbox:latest > /dev/null 2>&1; then
        echo ">>> Sandbox image missing. Building now..."
        docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
    fi
else
    echo "!!! WARNING: Docker not found. Repair loop will fail in production!"
fi

# 4. Launch with Gunicorn
# Using 2 workers and UvicornWorker for stability on 1GB RAM instances.
# We bind to 0.0.0.0 to allow Koyeb to route traffic to the container.
echo ">>> Launching Gunicorn..."
exec gunicorn api.main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:$PORT \
    --access-logfile - \
    --error-logfile - \
    --timeout 300
