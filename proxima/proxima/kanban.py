# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""The board's lanes, as a component, so cards can be dragged.

Streamlit has no drag and drop and no way to learn that a pointer crossed from
one column into another, so the lanes are drawn by the component in its own
iframe. It reports a move the moment a card is dropped; Python writes it to the
workspace and the board re-renders from the database as usual.

Keyboard works too — focus a card and press the left or right arrow — because
dragging is a mouse gesture and a board nobody can operate without one is a
board some people cannot operate at all.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_BUILD = Path(__file__).resolve().parent / "components" / "kanban"

_component = components.declare_component("proxima_kanban", path=str(_BUILD))


def kanban(
    *,
    columns: list[str],
    tickets: list[dict[str, Any]],
    show_sprint: bool = False,
    key: str = "kanban",
) -> dict | None:
    """Draw the board and return the last thing done to it.

    Returns a dict with ``kind`` of "move" (plus ``id`` and ``status``) or
    "delete" (plus ``id``), and a ``nonce`` so the caller can tell a fresh
    action from a re-run showing the same value again.
    """
    return _component(
        columns=columns,
        tickets=tickets,
        show_sprint=show_sprint,
        key=key,
        default=None,
    )
