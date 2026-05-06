#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — Launch script for the Laravel AI Repair Platform
# Run this INSIDE WSL (Ubuntu): bash start.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║      Laravel AI Repair Platform — WSL Startup Script     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Activate existing venv ────────────────────────────────────────────────
if [ ! -d "venv" ]; then
    echo "▶ Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    echo "▶ Activating existing venv..."
    source venv/bin/activate
fi

# ── 2. Check .env exists ─────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "▶ Copying .env.example to .env..."
    cp .env.example .env
fi

# ── 3. Check Docker and Build Sandbox ───────────────────────────────────────
echo "▶ Checking Docker daemon..."
FORCE_BUILD=false
for arg in "$@"; do
    if [ "$arg" == "--build" ]; then
        FORCE_BUILD=true
    fi
done

if docker info > /dev/null 2>&1; then
    if ! docker image inspect laravel-sandbox:latest > /dev/null 2>&1 || [ "$FORCE_BUILD" = true ]; then
        if [ "$FORCE_BUILD" = true ]; then
            echo "▶ Force rebuild requested. Rebuilding Sandbox (5-10 mins)..."
        else
            echo "▶ Sandbox image not found. Building (this can take 5-10 mins)..."
        fi
        docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
    else
        echo "   ✅ Sandbox image already built. Use --build to refresh."
    fi
else
    echo "   ⚠  Docker not running. Server will start, but repair won't work."
fi




# ── 5. Launch FastAPI Server ────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ⚡ Server starting at  http://localhost:8000            ║"
echo "║  📖 Swagger docs at     http://localhost:8000/docs       ║"
echo "║  🌐 Open frontend/index.html in your Windows browser     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Ensure data directory exists for SQLite
mkdir -p data

# Start server
uvicorn api.main:app --reload --reload-exclude "data/*" --reload-exclude "logs/*" --host 0.0.0.0 --port 8000
