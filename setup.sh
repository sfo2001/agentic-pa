#!/usr/bin/env bash
# One-command setup (Linux/macOS): hand off to install.py under a base
# interpreter, which creates a venv (or falls back to a venv-less --target
# install if the venv's python is policy-blocked). Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.10+ and re-run (or set PYTHON=…)." >&2
  exit 1
fi
exec "$PY" install.py "$@"
