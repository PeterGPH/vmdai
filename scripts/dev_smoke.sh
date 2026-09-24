#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
PORT="${VMD_AI_PORT:-8765}"
STORE_DIR="${VMD_AI_STORE_DIR:-$HOME/.vmdai/chats_smoke}"

"$ROOT_DIR/scripts/print_env_checks.sh"

"$PYTHON_BIN" "$ROOT_DIR/runtime/main.py" --host 127.0.0.1 --port "$PORT" --store-dir "$STORE_DIR" >/tmp/vmd_ai_runtime_smoke.log 2>&1 &
RUNTIME_PID=$!
trap 'kill "$RUNTIME_PID" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 0.1
done

PYTHONPATH="$ROOT_DIR/runtime:${PYTHONPATH:-}" "$PYTHON_BIN" - <<'PY'
import time
from vmd_ai_runtime.client import RuntimeClient

client = RuntimeClient(port=8765)
health = client.health()
print('[smoke] health:', health)

start = client.rpc('session.start', {
    'cwd': '.',
    'ui_mode': 'qt',
    'client_version': 'smoke',
    'platform': 'local',
})
print('[smoke] session.start:', start)
result = start['result']
sid = result['session_id']
client.session_token = result['session_token']
chat_id = result['chat_id']

send = client.rpc('chat.send', {
    'session_id': sid,
    'chat_id': chat_id,
    'text': 'hi smoke',
    'model': 'anthropic/claude-sonnet-4.6',
    'mode': 'work',
    'conversation_mode': 'local_first',
})
print('[smoke] chat.send:', send)

after = 0
seen = 0
for _ in range(40):
    polled = client.rpc('chat.events.poll', {'session_id': sid, 'after_seq': after, 'limit': 50})
    events = polled['result']['events']
    if events:
        seen += len(events)
        after = polled['result']['last_seq']
    if any(e.get('role') == 'assistant' and e.get('type') == 'message' for e in events):
        break
    time.sleep(0.1)

print('[smoke] events seen:', seen)
stop = client.rpc('session.stop', {'session_id': sid})
print('[smoke] session.stop:', stop)
PY

echo "[smoke] ok"
