#!/bin/bash
# test_repair.sh — Quick curl test for the repair endpoint
set -e

echo "=== 1. Health Check ==="
curl -s http://localhost:8000/api/health | python3 -m json.tool

echo ""
echo "=== 2. Submit Repair Job (Qwen) ==="
RESPONSE=$(curl -s -X POST http://localhost:8000/api/repair \
  -H "Content-Type: application/json" \
  -d '{
    "code": "<?php\nnamespace App\\Http\\Controllers\\Api;\n\nuse App\\Http\\Controllers\\Controller;\nuse Illuminate\\Http\\JsonResponse;\n\nclass StatusController extends Controller\n{\n    public function index(): JsonResponse\n    {\n        return response()->json([\n            \"status\" => \"ok\",\n            \"time\"   => Carbon::now()->toIso8601String(),\n        ]);\n    }\n}\n",
    "max_iterations": 3
  }')

echo "$RESPONSE" | python3 -m json.tool
SUBMISSION_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['submission_id'])")
echo "Submission ID: $SUBMISSION_ID"

echo ""
echo "=== 3. Streaming SSE Events ==="
echo "(Will stream for up to 5 minutes, Ctrl+C to stop)"
curl -s -N "http://localhost:8000/api/repair/${SUBMISSION_ID}/stream"
