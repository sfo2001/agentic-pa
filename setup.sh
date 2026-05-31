#!/usr/bin/env bash
# One-command setup (Linux/macOS): create a venv, install the packages, then run
# the guided setup wizard. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.12+ and re-run (or set PYTHON=…)." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtualenv (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

echo "Installing packages…"
python -m pip install --upgrade pip >/dev/null
# llm-wiki-tools is a required sibling checkout (not on PyPI) — install it editable
# FIRST so it backs the `llm-wiki-tools` dependency of agenda/frontend.
LWT="${LLM_WIKI_TOOLS:-../llm-wiki-tools}"
if [ ! -d "$LWT" ]; then
  echo "ERROR: llm-wiki-tools not found at '$LWT' (a required sibling checkout)." >&2
  echo "Clone it next to this repo (../llm-wiki-tools) or set LLM_WIKI_TOOLS=/path and re-run." >&2
  exit 1
fi
pip install -e "$LWT" -e ./agenda -e ./frontend -e ./presenter
pip install -r agenda/requirements-dev.txt -r frontend/requirements-dev.txt

echo
python -m frontend.setup_wizard
