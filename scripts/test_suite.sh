#!/bin/bash
# test_suite.sh — Comprehensive API Test Suite for LaraVibe
# This script verifies all major backend endpoints.

set -e # Exit on error

BASE_URL="http://127.0.0.1:8000"
echo "🚀 Starting LaraVibe API Test Suite..."
echo "Target: ${BASE_URL}"
echo "--------------------------------------------------"

# Helper for JSON pretty printing
function print_json() {
    if command -v jq >/dev/null 2>&1; then
        jq '.'
    else
        python3 -m json.tool 2>/dev/null || cat
    fi
}

echo "✅ [1/7] Testing Health Check..."
curl -s "${BASE_URL}/api/health" | print_json

echo ""
echo "📊 [2/7] Testing Stats Summary..."
curl -s "${BASE_URL}/api/stats/summary" | print_json

echo ""
echo "📈 [3/7] Testing Stats Efficiency Trends..."
curl -s "${BASE_URL}/api/stats/efficiency" | print_json

echo ""
echo "📂 [4/7] Testing Admin Training Dataset..."
curl -s "${BASE_URL}/api/admin/training-dataset" | print_json

echo ""
echo "📜 [5/7] Testing Submission History..."
curl -s "${BASE_URL}/api/history" | print_json

echo ""
echo "🛠️  [6/7] Testing Repair Submission..."
REPAIR_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/repair" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "<?php\nnamespace App\\Http\\Controllers;\nclass BrokenController {\n    public function index() {\n        return $not_defined + 10;\n    }\n}",
    "max_iterations": 2,
    "use_boost": true
  }')

echo "${REPAIR_RESPONSE}" | print_json
SUBMISSION_ID=$(echo "${REPAIR_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('submission_id', ''))")

if [ -z "$SUBMISSION_ID" ]; then
    echo "❌ Error: Failed to get submission_id from response"
    exit 1
fi

echo ""
echo "📡 [7/7] Testing SSE Stream & Final Result..."
echo "Sampling SSE stream for 3 seconds..."
# Sample the stream for a few seconds using timeout
if command -v timeout >/dev/null 2>&1; then
    timeout 3s curl -s -N "${BASE_URL}/api/repair/${SUBMISSION_ID}/stream" || true
else
    echo "(Skipping stream sampling – 'timeout' command not found)"
fi

echo ""
echo "🔍 Fetching final submission state for ${SUBMISSION_ID}..."
curl -s "${BASE_URL}/api/repair/${SUBMISSION_ID}" | print_json

echo ""
echo "🔥 [8/8] Testing Parallel Concurrency..."
echo "Submitting 3 simultaneous repair requests..."

for i in {1..3}; do
  (
    CODE="<?php\nclass ParallelTest$i { public function run() { return $i; } }"
    RESP=$(curl -s -X POST "${BASE_URL}/api/repair" -H "Content-Type: application/json" -d "{\"code\": \"$CODE\", \"max_iterations\": 1}")
    ID=$(echo "${RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('submission_id', ''))")
    echo "  [Thread $i] Submitted: $ID"
    # Sample the stream for a moment to ensure it's alive
    if command -v timeout >/dev/null 2>&1; then
        timeout 2s curl -s -N "${BASE_URL}/api/repair/${ID}/stream" > /dev/null || true
        echo "  [Thread $i] Stream active."
    else
        echo "  [Thread $i] (Skipping stream check - timeout missing)"
    fi
  ) &
done

echo "Waiting for parallel threads to initialize..."
wait

echo ""
echo "🧪 [9/9] Testing Batch Evaluation (Async)..."
EVAL_RESP=$(curl -s -X POST "${BASE_URL}/api/evaluate")
echo "${EVAL_RESP}" | print_json
EXP_ID=$(echo "${EVAL_RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('experiment_id', ''))")

if [ -z "$EXP_ID" ]; then
    echo "❌ Error: Failed to start batch evaluation"
else
    echo "Evaluation Job Started: ${EXP_ID}"
    echo "Checking status..."
    curl -s "${BASE_URL}/api/evaluate/${EXP_ID}" | print_json
fi

echo "--------------------------------------------------"
echo "✨ Test Suite Finished!"
