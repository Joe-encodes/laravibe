#!/bin/bash
# scripts/run_batch_eval.sh
# Triggers a batch evaluation across the entire dataset and polls for completion.

APP_URL="${APP_URL:-http://localhost:8000}"
MASTER_TOKEN="${MASTER_TOKEN:-change-me-in-production}"

echo "=========================================================="
echo "    LaraVibe Repair Platform — Batch Evaluation"
echo "    Target: $APP_URL"
echo "=========================================================="
echo ""

echo "🚀 Triggering Batch Evaluation..."
RESP=$(curl -s -X POST "$APP_URL/api/evaluate" \
     -H "Authorization: Bearer $MASTER_TOKEN" \
     -H "Content-Type: application/json")

EXP_ID=$(echo "$RESP" | grep -o '"experiment_id":"[^"]*' | cut -d'"' -f4)

if [ -z "$EXP_ID" ]; then
    echo "❌ Failed to start evaluation. Ensure backend is running."
    echo "Response: $RESP"
    exit 1
fi

echo "✅ Evaluation started: $EXP_ID"
echo "⏳ Polling for results (this may take 5-15 mins)..."

while true; do
    STATUS_RESP=$(curl -s -X GET "$APP_URL/api/evaluate/$EXP_ID" \
        -H "Authorization: Bearer $MASTER_TOKEN")
    STATUS=$(echo "$STATUS_RESP" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
    
    if [ "$STATUS" == "completed" ]; then
        echo ""
        echo "🎉 Evaluation Complete!"
        SUCCESS_RATE=$(echo "$STATUS_RESP" | grep -o '"success_rate_pct":[^,]*' | cut -d':' -f2)
        echo "📊 Success Rate: $SUCCESS_RATE%"
        
        echo "--------------------------------------------------------"
        echo " CASE ID                      | STATUS   | ITERS | SCORE "
        echo "--------------------------------------------------------"
        # Parse output for clean terminal table
        echo "$STATUS_RESP" | grep -o '"sample_file":"[^"]*\|"status":"[^"]*\|"iterations":[0-9]*\|"mutation_score":[0-9.]*' | awk -F'[:"]' '{
            if ($2 == "sample_file") file=$5;
            else if ($2 == "status") status=$5;
            else if ($2 == "iterations") iters=$3;
            else if ($2 == "mutation_score") {
                score=$3;
                printf " %-28s | %-8s | %-5s | %s%%\n", file, status, iters, score;
            }
        }'
        echo "--------------------------------------------------------"
        break
    elif [ "$STATUS" == "error" ]; then
        echo ""
        echo "❌ Evaluation failed with an infrastructure error!"
        echo "$STATUS_RESP"
        exit 1
    fi
    
    echo -n "."
    sleep 15
done
