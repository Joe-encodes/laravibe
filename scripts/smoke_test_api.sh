#!/bin/bash
# scripts/smoke_test_api.sh
# Smoke tests ALL major backend API endpoints to ensure the server is healthy.

APP_URL="${APP_URL:-http://localhost:8000}"
MASTER_TOKEN="${MASTER_TOKEN:-change-me-in-production}"

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

# 2. Stats Target
echo "📊 2. Checking /api/stats (Needs Authentication) ..."
STATS_RESP=$(curl -sL "$APP_URL/api/stats" -H "Authorization: Bearer $MASTER_TOKEN")
if echo "$STATS_RESP" | grep -q 'total_repairs'; then
    echo "   ✅ Stats OK"
else
    echo "   ❌ Stats failed. Check auth token or DB."
    echo "   Output: $STATS_RESP"
    exit 1
fi

# 3. History Target
echo "📜 3. Checking /api/history (Needs Authentication) ..."
HISTORY_RESP=$(curl -sL "$APP_URL/api/history?limit=1" -H "Authorization: Bearer $MASTER_TOKEN")
if echo "$HISTORY_RESP" | grep -q '"id"'; then
    echo "   ✅ History OK"
else
    echo "   ❌ History failed. Check auth token or DB."
    echo "   Output: $HISTORY_RESP"
    exit 1
fi

# 4. Repair Submission Queue Test
echo "🚀 4. Checking /api/repair (Job queueing) ..."
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
     -H "Authorization: Bearer $MASTER_TOKEN" \
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
