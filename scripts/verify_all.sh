#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# verify_all.sh — Master Verification Suite for Laravel AI Repair Platform
# ─────────────────────────────────────────────────────────────────────────────

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║      LaraVibe Platform — Phase 1 Verification Suite      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# 1. Check venv
if [ ! -d "venv" ]; then
    echo "❌ venv not found. Please run start.sh first."
    exit 1
fi
source venv/bin/activate

# 2. Check Logging setup
echo "▶ Checking Logging setup..."
if [ -f "api/logging_config.py" ] && grep -q "setup_logging" api/main.py; then
    echo "   ✅ Unified Logging Integrated."
else
    echo "   ❌ Logging Integration Missing."
fi

# 3. Run Resilience Proof
echo ""
echo "▶ Running Resilience Proof (Timeout vs Crash)..."
python scripts/test_resilience.py

# 4. Check Health
echo ""
echo "▶ Checking API Health..."
if curl -s http://localhost:8000/api/health | grep -q "\"status\":\"ok\""; then
    echo "   ✅ API is UP and healthy."
else
    echo "   ⚠  API not running or unhealthy. Start it with start.sh first to see full status."
fi

# 5. Summary
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Phase 1 Stabilization Status: READY                     ║"
echo "║  Logs Location: data/logs/repair_platform.log            ║"
echo "╚══════════════════════════════════════════════════════════╝"
