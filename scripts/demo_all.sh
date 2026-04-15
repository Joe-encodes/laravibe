#!/usr/bin/env bash
# scripts/demo_all.sh — Real-world demo of the full repair cycle (No Mocks)
# Shows Boost context and Mutation testing in a live run.

set -euo pipefail

# Colors for demonstration
GREEN='\033[0;32m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
YELLOW='\033[1;33m'
RESET='\033[0m'

API="http://localhost:8000"
CASE="dataset/case-001/code.php"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BLUE}║       LaraVibe — LIVE CAPACITY DEMONSTRATION             ║${RESET}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# 1. Check API
if ! curl -s "$API/api/health" | grep -q "\"status\":\"ok\""; then
    echo -e "${YELLOW}⚠  API is not running. Attempting to start it in background...${RESET}"
    echo -e "   Run 'uvicorn api.main:app --host 0.0.0.0' in another terminal first."
    exit 1
fi

echo -e "${PURPLE}▶ Submitting broken case: ${CASE}${RESET}"
CODE=$(cat "$CASE")
PAYLOAD=$(jq -n --arg code "$CODE" '{code: $code, max_iterations: 3, use_boost: true, use_mutation_gate: true}')

RESP=$(curl -s -X POST "$API/api/repair" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

SID=$(echo "$RESP" | jq -r '.submission_id')
echo -e "   ${GREEN}Submission ID: $SID${RESET}"
echo ""

echo -e "${PURPLE}▶ Streaming Live Feedback (SSE):${RESET}"
echo "--------------------------------------------------"

# Stream and highlights
curl -sN "$API/api/repair/$SID/stream" | while IFS= read -r line; do
  if [[ "$line" == data:* ]]; then
    EVENT=$(echo "${line#data: }" | jq -r '.event // empty')
    DATA=$(echo "${line#data: }" | jq -r '.data // empty')

    case "$EVENT" in
      iteration_start)
        echo -e "\n${BLUE}─── ITERATION $(echo "$DATA" | jq -r '.iteration') ───${RESET}"
        ;;
      boost_queried)
        echo -e "   ${YELLOW}⚡ [BOOST] Context successfully retrieved from Laravel Artisan${RESET}"
        ;;
      ai_thinking)
        echo -e "   🤖 ${GREEN}AI Diagnosis:${RESET} $(echo "$DATA" | jq -r '.diagnosis // "Thinking..."')"
        ;;
      pest_result)
        echo -e "   🧪 ${BLUE}Pest Test:${RESET} $(echo "$DATA" | jq -r '.status')"
        ;;
      mutation_result)
        echo -e "   🧬 ${PURPLE}Mutation Gate:${RESET} $(echo "$DATA" | jq -r '.score')% (Threshold: $(echo "$DATA" | jq -r '.threshold')%)"
        ;;
      patch_applied)
        echo -e "   🛠️  Applied patch: ${GREEN}$(echo "$DATA" | jq -r '.action')${RESET}"
        ;;
      complete)
        echo -e "\n${GREEN}✔ COMPLETE! Final Status: $(echo "$DATA" | jq -r '.status')${RESET}"
        echo -e "Final Mutation Score: ${PURPLE}$(echo "$DATA" | jq -r '.mutation_score')%${RESET}"
        break
        ;;
    esac
  fi
done

echo "--------------------------------------------------"
echo -e "${GREEN}Demo finished. Use 'python scripts/dump_last_log.py' for full audit log.${RESET}"
