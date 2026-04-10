#!/bin/bash
# test_qwen.sh — Submit a repair and stream the results
set -e

echo "=== Submitting repair to Qwen ==="
RESP=$(curl -s -X POST http://localhost:8000/api/repair \
  -H "Content-Type: application/json" \
  --data-binary @- <<'ENDJSON'
{
  "code": "<?php\nnamespace App\\Http\\Controllers\\Api;\n\nuse App\\Http\\Controllers\\Controller;\nuse Illuminate\\Http\\JsonResponse;\n\nclass StatusController extends Controller\n{\n    public function index(): JsonResponse\n    {\n        return response()->json([\n            'status' => 'ok',\n            'time'   => Carbon::now()->toIso8601String(),\n        ]);\n    }\n}\n",
  "max_iterations": 3
}
ENDJSON
)

echo "$RESP"
SID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['submission_id'])")
echo "ID: $SID"
echo ""
echo "=== Streaming ==="
timeout 300 curl -s -N "http://localhost:8000/api/repair/${SID}/stream" || true
echo ""
echo "=== Done ==="
