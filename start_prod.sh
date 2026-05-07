#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start_prod.sh — Production launch script for Laravel AI Repair Platform
# Optimized for cloud environments (Ubuntu/Koyeb)
# ─────────────────────────────────────────────────────────────────────────────
# set +e # Disable exit on error so we can at least launch Gunicorn if Docker fails

# 1. Environment Checks
export REPAIR_ENV="production"
PORT="${PORT:-8000}"

echo ">>> Starting LaraVibe in PRODUCTION mode on port $PORT"

# 2. Infrastructure Setup
# Ensure data and logs directories exist
mkdir -p data logs

# 3. Background Infrastructure Setup
echo ">>> Launching infrastructure in background..."
(
    # Docker Daemon Startup (DinD)
    echo ">>> Starting Docker daemon..."
    # We use vfs driver because overlay2 often fails in nested containers on cloud hosts
    dockerd --storage-driver=vfs 2>&1 | tee logs/docker.log &

    # Wait for Docker to be ready
    echo ">>> Waiting for Docker to wake up..."
    TIMEOUT=60
    while ! docker info > /dev/null 2>&1; do
        TIMEOUT=$((TIMEOUT - 1))
        if [ "$TIMEOUT" -le 0 ]; then
            echo "!!! ERROR: Docker daemon failed to start. Check logs/docker.log"
            exit 1
        fi
        sleep 1
    done

    echo ">>> Docker is alive. Starting background sandbox preparation..."
    if ! docker image inspect laravel-sandbox:latest > /dev/null 2>&1; then
        echo ">>> [Background] Sandbox image missing. Starting build (~10 mins)..."
        docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
        echo ">>> [Background] Sandbox image build COMPLETE."
    else
        echo ">>> [Background] Sandbox image already exists."
    fi
) &


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
