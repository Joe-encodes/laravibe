#!/bin/bash
# scripts/verify_batch.sh
# Triggers a batch evaluation and polls for completion.

API_URL="http://127.0.0.1:8000"

echo "🚀 Triggering Batch Evaluation..."
RESP=$(curl -s -X POST "$API_URL/api/evaluate")
EXP_ID=$(echo $RESP | grep -oP '"experiment_id":"\K[^"]+')

if [ -z "$EXP_ID" ]; then
    echo "❌ Failed to start evaluation. Response: $RESP"
    exit 1
fi

echo "✅ Evaluation started: $EXP_ID"
echo "⏳ Polling for results (this may take 10-15 mins)..."

while true; do
    STATUS_RESP=$(curl -s -X GET "$API_URL/api/evaluate/$EXP_ID")
    STATUS=$(echo $STATUS_RESP | grep -oP '"status":"\K[^"]+')
    
    if [ "$STATUS" == "completed" ]; then
        echo "🎉 Evaluation Complete!"
        SUCCESS_RATE=$(echo $STATUS_RESP | grep -oP '"success_rate_pct":\K[0-9.]+')
        echo "📊 Success Rate: $SUCCESS_RATE%"
        echo "📝 Results written to tests/integration/results/batch_report_boost_on.csv"
        echo "----------------------------------------------------"
        echo "CASE_ID | STATUS | ITERS | MUTATION"
        echo "----------------------------------------------------"
        # Extracting results list - simpler way to print
        echo $STATUS_RESP | grep -oP '"sample_file":"\K[^"]+|"status":"\K[^"]+|"iterations":\K[0-9]+|"mutation_score":\K[0-9.]+' | xargs -n4 echo | sed 's/ / | /g'
        break
    elif [ "$STATUS" == "error" ]; then
        echo "❌ Evaluation failed with error!"
        echo $STATUS_RESP
        exit 1
    fi
    
    echo -n "."
    sleep 30
done
