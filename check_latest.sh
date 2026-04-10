#!/bin/bash
# check_latest.sh — Show the latest 5 submissions
curl -s http://localhost:8000/api/history | python3 -c "
import sys, json
data = json.load(sys.stdin)
for x in data[:5]:
    sid = x['id'][:8]
    status = x['status']
    iters = x.get('total_iterations', 0)
    err = (x.get('error_summary') or '-')[:80]
    print(f'{sid}  {status:8s}  iters={iters}  {err}')
"
