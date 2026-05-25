#!/bin/bash
# scripts/run_single_case.sh
# Sends a specific broken code snippet to the backend and streams the repair execution logs.

APP_URL="${APP_URL:-http://localhost:8000}"

API_URL="$APP_URL/api/repair"

# Try to read MASTER_REPAIR_TOKEN from .env if not already set
if [ -z "$MASTER_TOKEN" ] && [ -f .env ]; then
    MASTER_TOKEN=$(grep -E "^MASTER_REPAIR_TOKEN=" .env | cut -d'=' -f2 | tr -d '\r')
fi
MASTER_TOKEN="${MASTER_TOKEN:-laravibe-repair-2026-safe-token}"

# Login to get JWT Token
echo "🔑 Logging in to retrieve session JWT ..."
LOGIN_RESP=$(curl -sL -X POST "$APP_URL/api/auth/login" \
     -H "Content-Type: application/json" \
     -d "{\"token\": \"$MASTER_TOKEN\"}")

JWT_TOKEN=$(echo "$LOGIN_RESP" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$JWT_TOKEN" ]; then
    echo "❌ Login failed. Check your MASTER_TOKEN."
    echo "Response: $LOGIN_RESP"
    exit 1
fi

# We simulate case-002: wrong_namespace.
PAYLOAD=$(cat << 'EOF'
{
  "code": "<?php\n\nnamespace App\\Http\\Api;\n\nclass UserController extends Controller\n{\n    public function index()\n    {\n        return response()->json(['message' => 'users index']);\n    }\n}\n",
  "max_iterations": 3,
  "use_boost": true,
  "use_mutation_gate": true
}
EOF
)

echo "🚀 Submitting broken code to Repair Platform ($API_URL) ..."
echo "--------------------------------------------------------"

# 1. Submit the repair request
RESPONSE=$(curl -s -X POST "$API_URL" \
     -H "Authorization: Bearer $JWT_TOKEN" \
     -H "Content-Type: application/json" \
     -d "$PAYLOAD")

# Extract submission_id
SUBMISSION_ID=$(echo "$RESPONSE" | grep -o '"submission_id":"[^"]*' | cut -d'"' -f4)

if [ -z "$SUBMISSION_ID" ]; then
    echo "❌ Failed to parse submission_id from response. Make sure the backend is running!"
    echo "Response: $RESPONSE"
    exit 1
fi

echo "✅ Accepted! Submission ID: $SUBMISSION_ID"
echo "📡 Attaching to live Event Stream..."
echo "--------------------------------------------------------"

# 2. Connect to the SSE stream to watch the repair loop
curl -N -s "$API_URL/$SUBMISSION_ID/stream?token=$JWT_TOKEN"

echo ""
echo "--------------------------------------------------------"
echo "✅ Single case test complete. Review the event stream above."
