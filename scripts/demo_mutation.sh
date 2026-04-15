#!/usr/bin/env bash
# scripts/demo_mutation.sh — Standalone demo of the Mutation Testing Gate
# Runs Pest with the --mutate flag to show score generation.

set -euo pipefail

IMAGE="laravel-sandbox:latest"
PURPLE='\033[0;35m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RESET='\033[0m'

echo -e "${PURPLE}▶ Initialising container for Mutation Demo...${RESET}"
CID=$(docker run -d --network=none $IMAGE sleep infinity)

cleanup() {
    docker rm -f "$CID" > /dev/null
}
trap cleanup EXIT

echo -e "${GREEN}1. Injecting a sample Controller & Test...${RESET}"

# Create a sample controller
docker exec -u sandbox "$CID" sh -c "cat > app/Http/Controllers/MathController.php <<'PHP'
<?php
namespace App\Http\Controllers;
class MathController {
    public function add(\$a, \$b) { return \$a + \$b; }
}
PHP"

# Create a sample test
docker exec -u sandbox "$CID" sh -c "mkdir -p tests/Feature && cat > tests/Feature/MathTest.php <<'PHP'
<?php
use App\\Http\\Controllers\\MathController;
// Pest 3 requires covers() to generate mutations
covers(MathController::class);

test('it adds numbers', function () {
    \$calc = new MathController();
    expect(\$calc->add(1, 2))->toBe(3);
});
PHP"


echo -e "${GREEN}2. Running Pest Functional Test...${RESET}"
docker exec -u sandbox "$CID" ./vendor/bin/pest tests/Feature/MathTest.php

echo ""
echo -e "${GREEN}3. Running Mutation Testing Gate (--mutate)...${RESET}"
echo -e "${BLUE}(This measures the quality of the tests, not just pass/fail)${RESET}"
docker exec -u sandbox "$CID" ./vendor/bin/pest --mutate tests/Feature/MathTest.php


echo ""
echo -e "${PURPLE}▶ Mutation demo complete. The platform parses that score to ensure high-quality repairs.${RESET}"
