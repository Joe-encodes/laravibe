#!/usr/bin/env bash
# Submit case-001 for repair and stream logs

CODE=$(cat dataset/case-001/code.php)
ESCAPED_CODE=$(echo "$CODE" | jq -Rs .)

echo "▶ Submitting repair request..."
RESPONSE=$(curl -s -X POST http://0.0.0.0:8000/api/repair \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change-me-in-production" \
  -d "{
    \"code\": $ESCAPED_CODE,
    \"max_iterations\": 3,
    \"use_boost\": true,
    \"use_mutation_gate\": false
  }")

SUBMISSION_ID=$(echo $RESPONSE | jq -r .submission_id)

if [ "$SUBMISSION_ID" == "null" ]; then
    echo "❌ Submission failed: $RESPONSE"
    exit 1
fi

echo "✅ Submission ID: $SUBMISSION_ID"
echo "▶ Streaming logs (Ctrl+C to stop)..."
echo ""

curl -N -s "http://0.0.0.0:8000/api/repair/$SUBMISSION_ID/stream?token=change-me-in-production"
