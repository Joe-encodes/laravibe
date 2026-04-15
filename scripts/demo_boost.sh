#!/usr/bin/env bash
# scripts/demo_boost.sh — Standalone demo of Laravel Boost Context Extraction
# Manually spins a container to show the schema and docs extraction.

set -euo pipefail

IMAGE="laravel-sandbox:latest"
PURPLE='\033[0;35m'
GREEN='\033[0;32m'
RESET='\033[0m'

echo -e "${PURPLE}▶ Spinning fresh sandbox container for Boost Demo...${RESET}"
CID=$(docker run -d --network=none $IMAGE sleep infinity)

# Helper to cleanup
cleanup() {
    echo -e "\n${PURPLE}▶ Destroying container $CID...${RESET}"
    docker rm -f "$CID" > /dev/null
}
trap cleanup EXIT

echo -e "Container alive: ${GREEN}$CID${RESET}"
echo ""

echo -e "${GREEN}1. Extracting DB Schema via Native Laravel 12 'db:show'...${RESET}"
docker exec -u sandbox "$CID" php artisan db:show --json

echo ""
echo -e "${GREEN}2. Extracting Application Routes via Native 'route:list'...${RESET}"
docker exec -u sandbox "$CID" php artisan route:list --json

echo ""
echo -e "${PURPLE}▶ Boost demo complete. We pivot to native framework commands to ensure 100% reliability${RESET}"
echo -e "${PURPLE}   while still providing the high-fidelity context required for the AI to fix your code.${RESET}"

