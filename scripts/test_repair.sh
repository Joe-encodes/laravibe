#!/bin/bash
# test_repair.sh — Quick curl test for the repair endpoint
set -e

BASE_URL="http://localhost:8000"

echo "=== 1. Health Check ==="
curl -s "${BASE_URL}/api/health" | python3 -m json.tool

echo ""
echo "=== 2. Submit Repair Job (Basic) ==="
# Use --data-binary to avoid shell interpolation issues with PHP code
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/repair" \
  -H "Content-Type: application/json" \
  --data-binary @- <<'ENDJSON'
{
  "code": "<?php\nnamespace App\\Http\\Controllers;\nclass BrokenController {\n    public function index() {\n        return $not_defined + 10;\n    }\n}",
  "max_iterations": 3
}
ENDJSON
)

echo "$RESPONSE" | python3 -m json.tool
SUBMISSION_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('submission_id', ''))")

if [ -z "$SUBMISSION_ID" ]; then
    echo "❌ Error: Failed to get submission_id"
    exit 1
fi
echo "Submission ID: $SUBMISSION_ID"

echo ""
echo "=== 3. Sampling SSE Events (5s) ==="
if command -v timeout >/dev/null 2>&1; then
    timeout 5s curl -s -N "${BASE_URL}/api/repair/${SUBMISSION_ID}/stream" || true
else
    echo "(Skipping stream sampling – 'timeout' command not found)"
fi

echo ""
echo "=== Done ==="
