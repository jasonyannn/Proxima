# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""The chat input: a custom component, because Streamlit's own cannot do this.

`st.text_input` only tells the server what you typed when you press Enter or
click away, so a correction that fires *while you are still writing* is not
possible with it. This component owns the textarea itself and talks back over
the standard component channel, which buys three things the built-in cannot do:

- auto-correction a moment after you stop typing, before anything is sent;
- an inline prediction of the next few words, accepted with Tab;
- Enter to send with Shift+Enter for a newline.

The model work happens in Python (see `agent.polish_prompt` and
`agent.predict_continuation`) and runs on the local Ollama instance, so none of
this costs anything per keystroke. The component only asks for it.
"""
from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_BUILD = Path(__file__).resolve().parent / "components" / "prompt_box"

_component = components.declare_component("proxima_prompt_box", path=str(_BUILD))


def prompt_box(
    *,
    value: str = "",
    revision: int = 0,
    placeholder: str = "",
    assist: bool = True,
    busy: bool = False,
    response: dict | None = None,
    key: str = "prompt_box",
) -> dict | None:
    """Render the input and return whatever the component last asked for.

    Returns a dict with a ``kind`` of "submit", "polish", "predict" or "sync",
    the ``text`` it concerns, and a ``nonce`` identifying the request. Python
    answers a request by passing ``response`` on the next render.

    ``revision`` is the server's way of overwriting the box (after a send, or
    when a voice transcript arrives): the component adopts ``value`` whenever
    this number changes, and otherwise leaves what you are typing alone.
    """
    return _component(
        value=value,
        revision=revision,
        placeholder=placeholder,
        assist=assist,
        busy=busy,
        response=response or {},
        key=key,
        default=None,
    )
