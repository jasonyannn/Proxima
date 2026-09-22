# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Chat tab: the conversation itself.

``render`` returns the pending exchange — the one the model has not answered
yet — because answering it is deliberately the last thing the app does, long
after every tab has painted. See "answering the pending message" at the foot of
app.py for why that ordering matters.
"""

from __future__ import annotations

import streamlit as st

try:
    from .. import theme
    from ..prompt_box import prompt_box
except ImportError:  # pragma: no cover
    import theme
    from prompt_box import prompt_box


def render(
    *,
    capture_speech,
    current_settings,
    handle_prompt_request,
    messages,
    render_reply,
    render_save_actions,
):
    """Draw the tab and hand back the exchange still awaiting an answer."""
    # Set by a save chip on the run before this one.
    toast = st.session_state.pop("save_toast", None)
    if toast:
        if current_settings()["persistent_alerts"]:
            # A toast fades after a few seconds. That is a deadline on reading,
            # which is exactly what some people cannot meet.
            st.session_state.setdefault("alerts", []).append(toast)
        else:
            st.toast(toast, icon="✅")

    alerts = st.session_state.get("alerts") or []
    if alerts:
        for position, message in enumerate(alerts):
            row, dismiss = st.columns([8, 1], gap="small")
            row.success(message, icon="✅")
            if dismiss.button("✕", key=f"alert{position}", help="Dismiss"):
                st.session_state.alerts.pop(position)
                st.rerun()

    # An exchange with agent=None is one whose question is already on screen but
    # whose reply has not been asked for yet. It keeps a slot in the transcript
    # and is answered at the bottom of the tab, once the page has been painted.
    pending = None

    if messages:
        theme.section("Transcript", index="01")
        for index, item in enumerate(messages):
            with st.chat_message("user"):
                st.markdown(item["user"])

            # Above the answer, not below it. An answer that is still streaming
            # grows by a line every repaint, and anything underneath slides down
            # the page as it does — a button nobody can reliably hit.
            render_save_actions(item, index)

            with st.chat_message("assistant"):
                if item.get("agent") is None:
                    pending = (index, item, st.empty())
                    pending[2].markdown("_Proxima is thinking..._")
                else:
                    render_reply(item["agent"], key=f"msg{index}")
    else:
        theme.empty_state(
            label="Session ready",
            title="Tell Proxima what your customers are saying",
            body="Paste raw feedback and it comes back as a structured product decision. Try:",
            example="We've had 20 customers asking for dark mode.",
        )

    st.divider()
    input_col, mic_col = st.columns([6, 1])

    # The mic renders first so a transcript can be pushed into the box before
    # the input itself is drawn.
    with mic_col:
        spoken = capture_speech()

    if spoken:
        st.session_state.box_text = spoken
        st.session_state.box_revision = st.session_state.get("box_revision", 0) + 1
        st.rerun()

    with input_col:
        # The input owns its own textarea (see prompt_box.py): Streamlit's does
        # not report keystrokes, and correcting text before it is sent needs
        # them. Enter sends, Shift+Enter starts a new line.
        request = prompt_box(
            value=st.session_state.get("box_text", ""),
            revision=st.session_state.get("box_revision", 0),
            placeholder="Customers keep asking for dark mode...",
            assist=st.session_state.get("setting_assist", True),
            # While an answer is generating, a rerun would restart it — so the
            # box stops asking for help until the reply has landed.
            busy=pending is not None,
            response=st.session_state.get("box_response"),
        )

    handle_prompt_request(request)

    with st.expander("Example prompts"):
        st.code(
            "We've had 20 customers asking for dark mode.\n"
            "Users keep reporting sign-out fails after refresh.\n"
            "Customer feedback: 'The checkout flow feels confusing and slow.'\n"
            "Should we prioritize the payment flow over the onboarding?",
            language="text",
        )

    # The model is not called here. It runs at the very bottom of this file,
    # once every tab has rendered — see "answering the pending message".

    return pending
