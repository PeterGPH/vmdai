#!/usr/bin/env bash
# Start the runtime in attach mode (no --announce): it accepts tokenless
# sessions and writes its launch token to ~/.vmdai/run/runtime-<port>.json
# (mode 0600) for a plugin started with VMD_AI_ATTACH=127.0.0.1:<port>.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${VMD_AI_PYTHON:-${PYTHON:-python3}}"
# The port: VMD_AI_PORT, else the port of VMD_AI_ATTACH=host:port (the
# address the plugin attaches to), else 8765.
ATTACH_PORT=""
if [ -n "${VMD_AI_ATTACH:-}" ]; then
  ATTACH_PORT="${VMD_AI_ATTACH##*:}"
fi
PORT="${VMD_AI_PORT:-${ATTACH_PORT:-8765}}"
STORE_DIR="${VMD_AI_STORE_DIR:-$HOME/.vmdai/chats}"
TOKEN_FILE="$HOME/.vmdai/run/runtime-${PORT}.json"

echo "[vmdai] runtime on 127.0.0.1:${PORT}; attach with VMD_AI_ATTACH=127.0.0.1:${PORT}" >&2
echo "[vmdai] launch token file: ${TOKEN_FILE}" >&2
exec "$PYTHON_BIN" "$ROOT_DIR/runtime/main.py" --host 127.0.0.1 --port "$PORT" --store-dir "$STORE_DIR"
