#!/bin/bash
# scripts/run_single_case.sh
# Sends a specific broken code snippet to the backend and streams the repair execution logs.

APP_URL="${APP_URL:-http://localhost:8000}"
MASTER_TOKEN="${MASTER_TOKEN:-change-me-in-production}"

API_URL="$APP_URL/api/repair"

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
     -H "Authorization: Bearer $MASTER_TOKEN" \
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
curl -N -s "$API_URL/$SUBMISSION_ID/stream?token=$MASTER_TOKEN"

echo ""
echo "--------------------------------------------------------"
echo "✅ Single case test complete. Review the event stream above."
