# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Import Proxima's modules from inside the MCP server package.

The app's modules sit in a directory that is not a Python package — Streamlit
runs ``app.py`` as a script, which is why every module there does the
``from .database import`` / ``from database import`` dance. The MCP server is
started a different way again (``python -m``, or by a client that sets its own
working directory), so neither half of that dance is reliable here.

Rather than repeat the try/except in every file, this module puts the app
directory on ``sys.path`` once and re-exports what the server needs. Everything
downstream just says ``pm.database.DatabaseManager``.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

accounts = importlib.import_module("accounts")
agent = importlib.import_module("agent")
competitors = importlib.import_module("competitors")
copyright_analyzer = importlib.import_module("copyright_analyzer")
database = importlib.import_module("database")
prompt = importlib.import_module("prompt")
workspace = importlib.import_module("workspace")

__all__ = [
    "APP_DIR",
    "accounts",
    "agent",
    "competitors",
    "copyright_analyzer",
    "database",
    "prompt",
    "workspace",
]
