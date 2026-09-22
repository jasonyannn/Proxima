# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""One module per tab.

Each exposes ``render(...)``, taking what it needs from the app as keyword
arguments — the open workspace, the chat's messages, and the few app-level
callbacks it cannot own. Nothing here reaches back into app.py, so a tab can be
read, and changed, without holding the rest of the application in your head.
"""
