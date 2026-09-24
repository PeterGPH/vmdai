#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
PORT="${VMD_AI_PORT:-8765}"

echo "[env] root: $ROOT_DIR"
echo "[env] python: $PYTHON_BIN"
"$PYTHON_BIN" - <<'PY'
import platform, sys
print('[env] python_version:', sys.version.replace('\n', ' '))
print('[env] platform:', platform.platform())
PY

echo "[env] runtime main exists: $ROOT_DIR/runtime/main.py"
if command -v nc >/dev/null 2>&1; then
  if nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; then
    echo "[env] port $PORT currently in use"
  else
    echo "[env] port $PORT available"
  fi
else
  echo "[env] nc not found; skipped port check"
fi
