#!/usr/bin/env bash
# Start the assistant (Linux/macOS): hand off to launch.py, which resolves the
# venv python (or a base interpreter + PYTHONPATH=.pysite) and starts the app.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.10+ (or set PYTHON=…)." >&2
  exit 1
fi
exec "$PY" launch.py "$@"
