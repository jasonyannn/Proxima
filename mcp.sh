#!/usr/bin/env bash
# Run Proxima as an MCP server.
#
# Same bootstrap as run.sh — shared virtualenv, dependencies installed on first
# use — so that an editor can point straight at this script without anyone
# having had to set the project up by hand first.
#
#   ./mcp.sh                            stdio, for VS Code / Claude / Codex
#   ./mcp.sh --transport http           streamable HTTP on 127.0.0.1:8765/mcp
#   ./mcp.sh --read-only                expose the analysis, refuse writes
#
# See docs/mcp.md for the per-client configuration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
APP="$ROOT/proxima/proxima"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN not found. Install Python 3.10+ and retry." >&2
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  # stderr: on stdio the client is parsing this process's stdout as protocol.
  echo "→ Creating virtualenv at .venv" >&2
  "$PYTHON_BIN" -m venv "$VENV"
fi

STAMP="$VENV/.mcp-deps-installed"
REQS="$APP/requirements-mcp.txt"
if [ ! -f "$STAMP" ] || [ "$REQS" -nt "$STAMP" ]; then
  echo "→ Installing MCP dependencies" >&2
  "$VENV/bin/python" -m pip install --quiet --upgrade pip >&2
  "$VENV/bin/python" -m pip install --quiet -r "$REQS" >&2
  touch "$STAMP"
fi

# The app's modules are a flat directory, not an installed package.
export PYTHONPATH="$APP${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m mcp_server "$@"
