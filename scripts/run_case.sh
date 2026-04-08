#!/usr/bin/env bash
# scripts/run_case.sh — Run one PHP file through the repair API and print results.
#
# Usage:
#   bash scripts/run_case.sh tests/fixtures/missing_model.php
#   bash scripts/run_case.sh samples/my_bug.php --max-iter 5
#
# Requires: curl, jq
# API must be running: uvicorn api.main:app --port 8000

set -euo pipefail

FILE="${1:?Usage: run_case.sh <file.php> [--max-iter N]}"
MAX_ITER="${3:-7}"
API="${REPAIR_API_URL:-http://localhost:8000}"

if [[ ! -f "$FILE" ]]; then
  echo "❌ File not found: $FILE"
  exit 1
fi

CODE=$(cat "$FILE")
echo "📤 Submitting: $FILE"
echo "   Max iterations: $MAX_ITER"
echo "   API: $API"
echo ""

# Submit
PAYLOAD=$(jq -n --arg code "$CODE" --argjson max_iter "$MAX_ITER" '{code: $code, max_iterations: $max_iter}')
RESPONSE=$(curl -s -X POST "$API/api/repair" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

SUB_ID=$(echo "$RESPONSE" | jq -r '.submission_id')

if [[ "$SUB_ID" == "null" || -z "$SUB_ID" ]]; then
  echo "❌ Submission failed:"
  echo "$RESPONSE" | jq .
  exit 1
fi

echo "✅ Submitted. ID: $SUB_ID"
echo "📡 Streaming progress..."
echo ""

# Stream SSE events
curl -sN "$API/api/repair/$SUB_ID/stream" | while IFS= read -r line; do
  if [[ "$line" == data:* ]]; then
    EVENT=$(echo "${line#data: }" | jq -r '.event // empty')
    DATA=$(echo "${line#data: }" | jq -r '.data // empty')

    case "$EVENT" in
      iteration_start)
        ITER=$(echo "$DATA" | jq -r '.iteration')
        MAX=$(echo "$DATA" | jq -r '.max')
        echo "── Iteration $ITER / $MAX ──"
        ;;
      log_line)
        echo "  $(echo "$DATA" | jq -r '.msg')"
        ;;
      ai_thinking)
        DIAG=$(echo "$DATA" | jq -r '.diagnosis // empty')
        [[ -n "$DIAG" ]] && echo "  🤖 $DIAG"
        ;;
      pest_result)
        STATUS=$(echo "$DATA" | jq -r '.status')
        [[ "$STATUS" == "pass" ]] && echo "  🧪 Pest: PASSED" || echo "  🧪 Pest: FAILED"
        ;;
      mutation_result)
        SCORE=$(echo "$DATA" | jq -r '.score')
        PASSED=$(echo "$DATA" | jq -r '.passed')
        [[ "$PASSED" == "true" ]] && echo "  🧬 Mutation: $SCORE% ✅" || echo "  🧬 Mutation: $SCORE% ⚠️"
        ;;
      complete)
        STATUS=$(echo "$DATA" | jq -r '.status')
        ITERS=$(echo "$DATA" | jq -r '.iterations')
        echo ""
        if [[ "$STATUS" == "success" ]]; then
          MSCORE=$(echo "$DATA" | jq -r '.mutation_score // "?"')
          echo "🎉 SUCCESS in $ITERS iteration(s)! Mutation score: $MSCORE%"
          echo ""
          echo "📥 Fetching repaired code..."
          curl -s "$API/api/repair/$SUB_ID" | jq -r '.final_code'
        else
          echo "😞 FAILED after $ITERS iterations."
        fi
        break
        ;;
    esac
  fi
done
