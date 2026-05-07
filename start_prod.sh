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

# 3. Docker Daemon Startup (DinD)
echo ">>> Starting Docker daemon..."
# We use vfs driver because overlay2 often fails in nested containers on cloud hosts
# We log output to logs/docker.log to help debug startup failures
dockerd --storage-driver=vfs > logs/docker.log 2>&1 &

# Wait for Docker to be ready
echo ">>> Waiting for Docker to wake up..."
TIMEOUT=30
while ! docker info > /dev/null 2>&1; do
    TIMEOUT=$((TIMEOUT - 1))
    if [ "$TIMEOUT" -le 0 ]; then
        echo "!!! ERROR: Docker daemon failed to start in time."
        break
    fi
    sleep 1
done

if docker info > /dev/null 2>&1; then
    echo ">>> Docker is alive. Verifying sandbox image..."
    if ! docker image inspect laravel-sandbox:latest > /dev/null 2>&1; then
        echo ">>> Sandbox image missing. Building now (this may take a minute)..."
        docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
    fi
else
    echo "!!! WARNING: Docker engine failed. Repair loop will NOT work!"
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
