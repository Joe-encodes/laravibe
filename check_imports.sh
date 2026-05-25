#!/bin/bash
cd '/mnt/c/Users/ESTHER/Desktop/Joseph'"'"'s Project/laravel-ai-proj/repair-platform'
./venv/bin/python3 -c "
import api.services.ai_service
import api.services.escalation_service
import api.services.repair.pipeline
import api.services.repair.orchestrator
print('=== All imports OK ===')

# Verify Executor pool composition
from api.services.ai_service import EXECUTOR_POOL, VERIFIER_POOL, REVIEWER_POOL, PLANNER_POOL
print('EXECUTOR_POOL:', EXECUTOR_POOL)
print('VERIFIER_POOL:', VERIFIER_POOL)
print('PLANNER_POOL:', PLANNER_POOL)
"
