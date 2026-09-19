#!/usr/bin/env bash
# End-to-end demo: delegation -> tool calls -> HITL approval -> resume -> memory recall.
# Usage: ./scripts/demo.sh [base-url]   (default http://localhost:8000)
set -euo pipefail

BASE="${1:-http://localhost:8000}"
USER_ID="demo-$(date +%s)"
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

wait_for() { # run_id, wanted status regex
  for _ in $(seq 1 60); do
    status=$(curl -fsS "$BASE/api/runs/$1" | json "d['status']")
    if [[ "$status" =~ $2 ]]; then echo "$status"; return 0; fi
    sleep 1
  done
  echo "timed out waiting for $2 (last: $status)" >&2; return 1
}

echo "==> Health"; curl -fsS "$BASE/health/ready"; echo

TASK="My name is Dana and I prefer concise answers. Order ORD-1042 arrived damaged - please refund \$250 and email me at dana@example.com to confirm."
echo "==> Starting run for $USER_ID"
RUN_ID=$(curl -fsS -X POST "$BASE/api/runs" -H 'content-type: application/json' \
  -d "{\"task\": \"$TASK\", \"user_id\": \"$USER_ID\"}" | json "d['id']")
echo "run: $RUN_ID"

for step in 1 2; do
  wait_for "$RUN_ID" 'awaiting_approval' >/dev/null
  APPROVAL=$(curl -fsS "$BASE/api/runs/$RUN_ID" | json "d['pending_approval']")
  APPROVAL_ID=$(echo "$APPROVAL" | python3 -c "import ast,sys; print(ast.literal_eval(sys.stdin.read())['id'])")
  echo "==> Paused for approval #$step: $(echo "$APPROVAL" | python3 -c "import ast,sys; a=ast.literal_eval(sys.stdin.read()); print(a['tool_name'], '-', a['reason'])")"
  curl -fsS -X POST "$BASE/api/approvals/$APPROVAL_ID/decision" -H 'content-type: application/json' \
    -d '{"decision": "approve", "reviewer": "demo-script"}' >/dev/null
  echo "    approved"
done

echo "==> Final status: $(wait_for "$RUN_ID" 'completed|failed')"
curl -fsS "$BASE/api/runs/$RUN_ID" | json "d['final_answer']"

echo "==> Trace"
curl -fsS "$BASE/api/runs/$RUN_ID/events" | python3 -c "
import json, sys
for e in json.load(sys.stdin):
    d = e['data']; extra = d.get('tool') or d.get('next') or ''
    print(f\"  {e['id']:>5} {e['type']:<20} {e['agent'] or '':<11} {extra}\")"

echo "==> Long-term memories"
curl -fsS "$BASE/api/memories?user_id=$USER_ID" | python3 -c "
import json, sys
for m in json.load(sys.stdin): print('  -', m['kind'], ':', m['content'])"

echo "==> Second run (new thread) recalls memory"
RUN2=$(curl -fsS -X POST "$BASE/api/runs" -H 'content-type: application/json' \
  -d "{\"task\": \"Write a short welcome note for me\", \"user_id\": \"$USER_ID\"}" | json "d['id']")
wait_for "$RUN2" 'completed|failed' >/dev/null
curl -fsS "$BASE/api/runs/$RUN2" | json "d['final_answer']"
