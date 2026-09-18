# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Proxima over the Model Context Protocol.

``python -m mcp_server`` from the app directory, or ``./mcp.sh`` from the
repository root, which bootstraps the virtualenv first.
"""
from .context import Context, ResolutionError, context_from_env
from .server import build_server

__all__ = ["Context", "ResolutionError", "context_from_env", "build_server"]
