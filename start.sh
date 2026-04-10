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
if docker info > /dev/null 2>&1; then
    if ! docker image inspect laravel-sandbox:latest > /dev/null 2>&1; then
        echo "▶ Sandbox image not found. Building (this can take 5-10 mins)..."
        # Pure legacy build — no flags, no buildkit, just the basics
        docker build -t laravel-sandbox:latest ./docker/laravel-sandbox/
    else
        echo "   ✅ Sandbox image already built."
    fi
else
    echo "   ⚠  Docker not running. Server will start, but repair won't work."
fi

# ── 4. Launch FastAPI Server ────────────────────────────────────────────────
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
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
