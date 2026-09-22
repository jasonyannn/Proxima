# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Display constants shared by the tabs.

Vocabulary, not logic: the words a status can take and the glyph or pill tone
each one wears. They live here rather than in app.py because only the tabs read
them, and a constant defined three screens from its only use is a constant that
drifts out of step with it.
"""

from __future__ import annotations

try:
    from ..competitors import STATUS_MATCH, STATUS_PARTIAL, STATUS_UNKNOWN
except ImportError:  # pragma: no cover
    from competitors import STATUS_MATCH, STATUS_PARTIAL, STATUS_UNKNOWN

# --- vocabulary ----------------------------------------------------------

LEVELS = ["High", "Medium", "Low"]
FEATURE_STATUSES = ["Backlog", "Planned", "In Progress", "Shipped"]
COLUMNS = ["Backlog", "To do", "In Progress", "Done"]
SPRINT_STATES = ["Planned", "Active", "Finished"]

# --- how each one reads --------------------------------------------------

STATUS_ICON = {STATUS_MATCH: "✅", STATUS_PARTIAL: "🟡", "Gap": "❌", STATUS_UNKNOWN: "·"}
RISK_COLOR = {"Low": "🟢", "Moderate": "🟡", "Elevated": "🟠", "High": "🔴"}
THREAT_COLOR = {"Low": "🟢", "Moderate": "🟡", "High": "🔴"}
STATUS_DOT = {"High": "🔴", "Moderate": "🟠", "Low": "🟡", "Info": "🔵"}

# Threat and risk levels map onto the pill tones in the theme.
RISK_TONE = {
    "Low": "ok",
    "Moderate": "warn",
    "Elevated": "warn",
    "High": "danger",
    "Unknown": "",
}
