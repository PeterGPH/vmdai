#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
PORT="${VMD_AI_PORT:-8765}"
STORE_DIR="${VMD_AI_STORE_DIR:-$HOME/.vmdai/chats}"

exec "$PYTHON_BIN" "$ROOT_DIR/runtime/main.py" --host 127.0.0.1 --port "$PORT" --store-dir "$STORE_DIR"
