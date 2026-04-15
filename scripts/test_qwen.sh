#!/bin/bash
# test_qwen.sh — Submit a repair targeting Qwen model specifically
set -e

BASE_URL="http://localhost:8000"

echo "=== 1. Health Check ==="
curl -s "${BASE_URL}/api/health" | python3 -m json.tool

echo ""
echo "=== 2. Submitting repair to Qwen ==="
RESP=$(curl -s -X POST "${BASE_URL}/api/repair" \
  -H "Content-Type: application/json" \
  --data-binary @- <<'ENDJSON'
{
  "code": "<?php\nnamespace App\\Http\\Controllers\\Api;\nuse App\\Http\\Controllers\\Controller;\nclass StatusController extends Controller\n{\n    public function index()\n    {\n        return response()->json([\n            'status' => 'ok',\n            'time'   => Carbon::now()->toIso8601String(),\n        ]);\n    }\n}\n",
  "max_iterations": 3,
  "use_boost": true
}
ENDJSON
)

echo "$RESP" | python3 -m json.tool
SID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('submission_id', ''))")

if [ -z "$SID" ]; then
    echo "❌ Error: Failed to get submission_id"
    exit 1
fi
echo "ID: $SID"

echo ""
echo "=== 3. Streaming (30s sample) ==="
if command -v timeout >/dev/null 2>&1; then
    timeout 30s curl -s -N "${BASE_URL}/api/repair/${SID}/stream" || true
else
    echo "(Skipping stream sampling – 'timeout' command not found)"
    curl -s -N "${BASE_URL}/api/repair/${SID}/stream"
fi

echo ""
echo "=== Done ==="
