#!/bin/bash
# check_result.sh — Check the result of the last repair
SID="${1:-d76481f1-4de0-4eb8-bd06-fbce35ff845e}"
echo "=== Submission $SID ==="
curl -s "http://localhost:8000/api/repair/${SID}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"Status: {d['status']}\")
print(f\"Iterations: {d.get('total_iterations', 0)}\")
for it in d.get('iterations', []):
    n = it['iteration_num']
    err = (it.get('error_logs') or '')[:200]
    print(f'  [{n}] {err}')
"
