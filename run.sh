#!/usr/bin/env bash
# Bootstrap and launch Proxima.
#
# Proxima is a Python/Streamlit app, not a Node app. This script exists so that
# `npm run dev` (and `./run.sh`) both work regardless of which one you reach for.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
APP="$ROOT/proxima/proxima/app.py"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN not found. Install Python 3.10+ and retry." >&2
  exit 1
fi

# Create the virtualenv on first run.
if [ ! -x "$VENV/bin/python" ]; then
  echo "→ Creating virtualenv at .venv"
  "$PYTHON_BIN" -m venv "$VENV"
fi

# Install dependencies only when requirements.txt is newer than the last install.
STAMP="$VENV/.deps-installed"
REQS="$ROOT/proxima/proxima/requirements.txt"
if [ ! -f "$STAMP" ] || [ "$REQS" -nt "$STAMP" ]; then
  echo "→ Installing dependencies"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -r "$REQS"
  touch "$STAMP"
fi

# The agent talks to a local Ollama server. Warn rather than fail: the app
# degrades to rule-based replies and both analysers work without it.
if ! curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "⚠  Ollama is not responding on http://localhost:11434"
  echo "   Chat replies will fall back to rule-based output."
  echo "   To enable the LLM:  ollama serve   (then: ollama pull llama3.2)"
  echo
fi

echo "→ Starting Proxima at http://localhost:8501"
# --server.headless keeps Streamlit from blocking on its first-run email prompt.
exec "$VENV/bin/streamlit" run "$APP" --server.headless true "$@"
