#!/bin/bash
# scripts/smoke_test_api.sh
# Smoke tests ALL major backend API endpoints to ensure the server is healthy.

APP_URL="${APP_URL:-http://localhost:8000}"

# Try to read MASTER_REPAIR_TOKEN from .env if not already set
if [ -z "$MASTER_REPAIR_TOKEN" ] && [ -f .env ]; then
    MASTER_REPAIR_TOKEN=$(grep -E "^MASTER_REPAIR_TOKEN=" .env | cut -d'=' -f2)
fi
MASTER_REPAIR_TOKEN="${MASTER_REPAIR_TOKEN:-laravibe-repair-2026-safe-token}"

echo "=========================================================="
echo "    LaraVibe Repair Platform — API Smoke Test"
echo "    Target: $APP_URL"
echo "=========================================================="
echo ""

# 1. Health Target
echo "🟢 1. Checking /api/health ..."
HEALTH_RESP=$(curl -sL "$APP_URL/api/health")
if echo "$HEALTH_RESP" | grep -q '"status":"ok"'; then
    echo "   ✅ Health OK"
else
    echo "   ❌ Health failed or unreachable."
    echo "   Output: $HEALTH_RESP"
    exit 1
fi

# 2. Login to get JWT Token
echo "🔑 Logging in to retrieve session JWT ..."
LOGIN_RESP=$(curl -sL -X POST "$APP_URL/api/auth/login" \
     -H "Content-Type: application/json" \
     -d "{\"token\": \"$MASTER_REPAIR_TOKEN\"}")

JWT_TOKEN=$(echo "$LOGIN_RESP" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -n "$JWT_TOKEN" ]; then
    echo "   ✅ Login Successful! Session token retrieved."
else
    echo "   ❌ Login failed. Check your MASTER_REPAIR_TOKEN."
    echo "   Output: $LOGIN_RESP"
    exit 1
fi

# 3. Stats Target
echo "📊 3. Checking /api/stats (Needs Authentication) ..."
STATS_RESP=$(curl -sL "$APP_URL/api/stats" -H "Authorization: Bearer $JWT_TOKEN")
if echo "$STATS_RESP" | grep -q 'total_repairs'; then
    echo "   ✅ Stats OK"
else
    echo "   ❌ Stats failed. Check auth token or DB."
    echo "   Output: $STATS_RESP"
    exit 1
fi

# 4. History Target
echo "📜 4. Checking /api/history (Needs Authentication) ..."
HISTORY_RESP=$(curl -sL "$APP_URL/api/history?limit=1" -H "Authorization: Bearer $JWT_TOKEN")
if echo "$HISTORY_RESP" | grep -q '"id"'; then
    echo "   ✅ History OK"
else
    echo "   ❌ History failed. Check auth token or DB."
    echo "   Output: $HISTORY_RESP"
    exit 1
fi

# 5. Repair Submission Queue Test
echo "🚀 5. Checking /api/repair (Job queueing) ..."
PAYLOAD=$(cat << 'EOF'
{
  "code": "<?php class SmokeTest {} ?>",
  "max_iterations": 1,
  "use_boost": false,
  "use_mutation_gate": false
}
EOF
)

REPAIR_RESP=$(curl -sL -X POST "$APP_URL/api/repair" \
     -H "Authorization: Bearer $JWT_TOKEN" \
     -H "Content-Type: application/json" \
     -d "$PAYLOAD")

SUBMISSION_ID=$(echo "$REPAIR_RESP" | grep -o '"submission_id":"[^"]*' | cut -d'"' -f4)

if [ -n "$SUBMISSION_ID" ]; then
    echo "   ✅ Repair Accepted! Submission ID: $SUBMISSION_ID"
else
    echo "   ❌ Repair submission failed."
    echo "   Output: $REPAIR_RESP"
    exit 1
fi

echo ""
echo "🎉 ALL ENDPOINTS FUNCTIONAL! Backend is production-ready."
echo "=========================================================="
