# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""The sidebar: who you are, what you are working on, and how it behaves.

Three sections, in the order you reach for them — the projects and chats you
move between, the workspace the open chat owns, and the settings that change
how Proxima answers.

It takes the app's chat operations as arguments rather than importing them.
They mutate session state that app.py owns, and a sidebar that reached back
into app.py to get at them would make the two impossible to read apart.
"""

from __future__ import annotations

import streamlit as st

try:
    from . import accessibility, accounts, report, theme, workspace
except ImportError:  # pragma: no cover
    import accessibility, accounts, report, theme, workspace


LANGUAGES = [
    "English",
    "Spanish",
    "French",
    "German",
    "Portuguese",
    "Italian",
    "Dutch",
    "Hindi",
    "Japanese",
    "Korean",
    "Chinese (Simplified)",
    "Arabic",
]


def render(
    *,
    USER,
    chat_title,
    current_project,
    db,
    delete_chat,
    delete_project,
    get_database,
    messages,
    move_chat,
    new_chat,
    new_project,
    remember_sessions,
):
    """Draw the sidebar."""
    with st.sidebar:
        who, out = st.columns([3, 1], gap="small")
        who.caption(f"Signed in as **{USER['name']}**")
        if out.button("Exit", help=f"Sign out of {USER['email']}", use_container_width=True):
            # Sign out means stay out: without this the next page load reads the
            # remembered session straight back in.
            accounts.forget()
            # Drop the cached workspace handles with the session: the next account
            # to sign in must not inherit this one's open databases.
            get_database.clear()
            for key in ("user", "chats", "current_chat_id", "chat_counter",
                        "chat_profile", "projects", "project_counter",
                        "setting_memory_scope", "set_colour_alone_inverted"):
                st.session_state.pop(key, None)
            for key in accessibility.DEFAULTS:
                st.session_state.pop(f"set_{key}", None)
            st.rerun()

        theme.section("Projects", index="01")

        def render_chat_row(chat_id: str) -> None:
            """One selectable chat, with its rename / move / delete menu."""
            title = chat_title(chat_id)
            active = chat_id == st.session_state.current_chat_id
            open_col, menu_col = st.columns([5, 1], gap="small")

            with open_col:
                # Streamlit stamps `st-key-<widget key>` onto each element
                # container, which is the only stable way to style one button
                # differently from its identical siblings. The theme paints
                # anything keyed `pxactive_` as the selected session.
                key = f"pxactive_{chat_id}" if active else f"select_{chat_id}"
                if st.button(title, use_container_width=True, key=key):
                    st.session_state.current_chat_id = chat_id
                    st.rerun()

            with menu_col:
                with st.popover("⋮", use_container_width=True, help="Rename, move or delete"):
                    renamed = st.text_input("Rename", value=title, key=f"rename_{chat_id}")
                    if st.button("Save", key=f"save_{chat_id}", use_container_width=True):
                        st.session_state.chats[chat_id]["title"] = renamed.strip()
                        remember_sessions()
                        st.rerun()

                    if st.session_state.projects:
                        options = [None] + list(st.session_state.projects)
                        here = st.session_state.chats[chat_id].get("project_id")
                        chosen = st.selectbox(
                            "Project",
                            options=options,
                            index=options.index(here) if here in options else 0,
                            format_func=lambda pid: (
                                st.session_state.projects[pid]["name"] if pid else "No project"
                            ),
                            key=f"move_{chat_id}",
                        )
                        if chosen != here:
                            move_chat(chat_id, chosen)
                            st.rerun()

                    if st.button(
                        "Delete chat", key=f"delete_{chat_id}", use_container_width=True
                    ):
                        delete_chat(chat_id)
                        st.rerun()

        make_col, new_col = st.columns(2, gap="small")
        if make_col.button("New project", use_container_width=True):
            st.session_state.current_chat_id = new_chat(new_project())
            st.rerun()
        if new_col.button("New chat", use_container_width=True, type="primary"):
            new_chat()
            st.rerun()

        open_project_id = (st.session_state.chats.get(
            st.session_state.current_chat_id, {}
        ) or {}).get("project_id")

        for project_id, project in st.session_state.projects.items():
            filed = workspace.chats_in_project(st.session_state.chats, project_id)
            # The project holding the open chat is the one you are working in, so
            # it is the one that should already be open when the page paints.
            # "· 1" read as a version or an index. Say what the number counts.
            label = f"{project['name']}  ·  {len(filed)} chat" + ("" if len(filed) == 1 else "s")

            with st.expander(label, expanded=project_id == open_project_id):
                # Chats first: picking one is why a project gets opened. The brief
                # and the name are settings — reached now and then, not every time,
                # so they fold away instead of sitting between you and the list.
                for chat_id in filed:
                    render_chat_row(chat_id)
                if not filed:
                    st.caption("No chats in this project yet.")

                if st.button(
                    "New chat here", key=f"add_{project_id}", use_container_width=True
                ):
                    new_chat(project_id)
                    st.rerun()

                with st.popover("Project settings", use_container_width=True):
                    brief = st.text_area(
                        "Project memory",
                        value=project.get("brief", ""),
                        key=f"brief_{project_id}",
                        height=90,
                        help=(
                            "What this project is about. Goes into every prompt for its "
                            "chats, above anything recalled from the transcripts."
                        ),
                        placeholder="A no-code shop builder for independent makers. "
                        "Mobile-first, sells to non-technical owners.",
                    )
                    if brief != project.get("brief", ""):
                        st.session_state.projects[project_id]["brief"] = brief
                        remember_sessions()

                    renamed = st.text_input(
                        "Name", value=project["name"], key=f"pname_{project_id}"
                    )
                    if renamed.strip() and renamed.strip() != project["name"]:
                        st.session_state.projects[project_id]["name"] = renamed.strip()
                        remember_sessions()
                        st.rerun()

                    st.divider()

                    # Behind the same fold as the settings, and behind a tick of its
                    # own: deleting a project should not be one stray click away
                    # from opening a chat inside it.
                    st.caption(
                        "Deleting the project keeps the chats inside — everything "
                        "saved in them survives, they just come out of the project."
                    )
                    also = st.checkbox(
                        f"Delete the {len(filed)} chat" + ("" if len(filed) == 1 else "s") + " too",
                        key=f"purge_{project_id}",
                    )
                    if st.button(
                        "Delete project", key=f"pdel_{project_id}", use_container_width=True
                    ):
                        delete_project(project_id, drop_chats=also)
                        if st.session_state.current_chat_id not in st.session_state.chats:
                            st.session_state.current_chat_id = next(
                                iter(st.session_state.chats), None
                            )
                        st.rerun()

        unfiled = workspace.chats_in_project(st.session_state.chats, None)
        if unfiled and st.session_state.projects:
            st.caption("Not in a project")
        for chat_id in unfiled:
            render_chat_row(chat_id)

        if not st.session_state.chats:
            st.caption("No sessions yet — start one above.")

        st.divider()
        theme.section("Workspace", index="02")
        here = current_project()
        if here:
            st.caption(f"In project **{here['name']}**")
        theme.pills(
            [
                (f"{len(db.list_features())} features", "accent"),
                (f"{len(db.list_competitors())} competitors", ""),
                (f"{len(db.list_competitor_features())} rival", ""),
            ]
        )

        # Export lives here rather than on a tab because it is not about any one
        # tab: it compiles all of them. The sidebar is the only place in reach
        # whichever tab you are reading when you decide to send this to someone.
        messages_here = messages
        # Always on screen, greyed rather than hidden. A control that only exists
        # once the workspace is full cannot be found by someone looking for it in
        # an empty one, and they conclude the feature was never built.
        nothing_here = report.is_empty(db, messages_here)
        st.download_button(
            "Download PDF report",
            # Built on click rather than every rerun: a long transcript takes a
            # moment to typeset, and the sidebar redraws on every keystroke.
            data=lambda: report.build(db, here, messages_here),
            file_name=report.filename(here),
            mime="application/pdf",
            use_container_width=True,
            disabled=nothing_here,
            help="Everything in this workspace — features, board, competitors, IP checks and this chat — as one PDF.",
        )

        if nothing_here:
            # The part that is genuinely not obvious: a workspace belongs to a
            # chat, not to the account. Empty here says nothing about the chat
            # above it, so point at the ones that do have something to export.
            elsewhere = [
                chat_title(other_id)
                for other_id in st.session_state.chats
                if other_id != st.session_state.current_chat_id
                and not report.is_empty(
                    get_database(other_id, USER["id"]),
                    st.session_state.chats[other_id].get("messages") or [],
                )
            ]
            if elsewhere:
                named = ", ".join(f"**{name}**" for name in elsewhere[:3])
                st.caption(
                    f"This chat is empty. Every chat keeps its own workspace — "
                    f"there is work to export in {named}."
                )
            else:
                st.caption("Nothing to export yet — save a feature or run a check first.")

        st.divider()
        theme.section("Settings", index="03")

        st.selectbox(
            "Reply language",
            options=LANGUAGES,
            key="setting_language",
            help="Proxima answers in this language whatever you type in.",
        )

        st.radio(
            "Answer length",
            options=list(accessibility.CHOICES["reply_length"]),
            format_func=lambda v: accessibility.LABELS["reply_length"][v],
            key="set_reply_length",
            on_change=remember_sessions,
            horizontal=True,
            help="How much working Proxima shows.",
        )

        st.radio(
            "Memory",
            options=list(workspace.SCOPES),
            format_func=lambda scope: workspace.SCOPE_LABELS[scope],
            key="setting_memory_scope",
            on_change=remember_sessions,
            help="How far back Proxima is allowed to look when answering.",
        )

        scope = st.session_state.get("setting_memory_scope", workspace.DEFAULT_SCOPE)
        if scope == "off":
            st.caption(
                "Only the open conversation. Nothing from your other chats reaches "
                "the model."
            )
        elif scope == "project":
            st.caption(
                "The project's brief, plus a digest of the other chats filed under "
                "it. Chats about other products stay out — which is the point: a "
                "model given every conversation at once averages them together."
            )
            if current_project() is None:
                st.caption(
                    "⚠ This chat is not in a project yet, so there is nothing to "
                    "recall. Put it in one from its ⋮ menu."
                )
        else:
            st.caption(
                "A digest of every chat on this account, each tagged with the "
                "project it came from. Broadest, and the most likely to bring an "
                "unrelated product into an answer."
            )

        st.caption(
            "Whatever the setting, this stays on this machine and does not change "
            "the model's weights — it is recall, not training."
        )

        st.toggle(
            "Prompt assist",
            value=st.session_state.get("setting_assist", True),
            key="setting_assist",
            help="Corrects and predicts as you type, before anything is sent.",
        )
        st.caption(
            "A moment after you stop typing, your message is tidied up — spelling, "
            "grammar, punctuation — and the next few words are offered in grey; "
            "press Tab to take them. It runs on the local model, so it costs "
            "nothing and never leaves this machine. Undo is always one click away."
        )

        with st.expander("Accessibility"):
            st.caption("**Seeing**")
            st.radio(
                "Text size",
                options=list(accessibility.CHOICES["text_scale"]),
                format_func=lambda v: accessibility.LABELS["text_scale"][v],
                key="set_text_scale",
                on_change=remember_sessions,
                horizontal=True,
            )
            st.radio(
                "Contrast",
                options=list(accessibility.CHOICES["contrast"]),
                format_func=lambda v: accessibility.LABELS["contrast"][v],
                key="set_contrast",
                on_change=remember_sessions,
                horizontal=True,
                help="Raises text and hairlines above the WCAG AA ratio everywhere.",
            )
            st.toggle(
                "Reading font",
                key="set_reading_font",
                on_change=remember_sessions,
                help="Swaps the interface to Lexend, designed for reading proficiency.",
            )

            st.radio(
                "Chart colours",
                options=list(accessibility.CHOICES["chart_colour"]),
                format_func=lambda v: accessibility.LABELS["chart_colour"][v],
                key="set_chart_colour",
                on_change=remember_sessions,
            )
            choice = st.session_state.get("set_chart_colour", "default")
            if choice == "separated":
                st.caption(
                    f"Caps a chart at {accessibility.SEPARATED_CAP} coloured series "
                    "and folds the rest into “Other”. Those three are the ones that "
                    "stay apart under protanopia and deuteranopia when any two marks "
                    "can sit side by side; a fourth hue does not."
                )
            elif choice == "one_hue":
                st.caption(
                    "Identity by lightness alone, which survives every kind of "
                    "colour blindness. Values are printed on the marks, because "
                    "with one hue the colour is carrying nothing."
                )
            else:
                st.caption(
                    "The measured palette: it already clears the colour-vision "
                    "separation target for neighbouring marks."
                )

            st.toggle(
                "Never use colour alone",
                value=not st.session_state.get("set_colour_alone", True),
                key="set_colour_alone_inverted",
                on_change=remember_sessions,
                help="Prints values on every mark, dashes each line, and opens the "
                     "table under each chart.",
            )

            st.caption("**Moving**")
            st.radio(
                "Motion",
                options=list(accessibility.CHOICES["motion"]),
                format_func=lambda v: accessibility.LABELS["motion"][v],
                key="set_motion",
                on_change=remember_sessions,
                horizontal=True,
                help="Reduced stops animations and the typing cursor on answers.",
            )
            st.toggle(
                "Larger click targets",
                key="set_big_targets",
                on_change=remember_sessions,
                help="Raises every button and input to the 44px WCAG target size.",
            )
            st.toggle(
                "Visible keyboard focus",
                key="set_focus_ring",
                on_change=remember_sessions,
                help="Draws a high-visibility ring around whatever Tab has landed on.",
            )

            st.caption("**Hearing and attention**")
            st.toggle(
                "Alerts stay until dismissed",
                key="set_persistent_alerts",
                on_change=remember_sessions,
                help="Confirmations stay on screen instead of fading after a moment.",
            )
            st.caption(
                "Proxima plays no audio and never puts information in sound alone, "
                "so nothing here needs captions. Voice input is optional and lands "
                "in the box as text you can edit before sending."
            )

            st.caption(
                "Not settings, because they would be labels on nothing: Streamlit "
                "owns the widget DOM, so the app cannot add screen-reader labelling "
                "or change tab order. What it can do instead is here — every chart "
                "has a table, every risk colour ships with a word, and every "
                "diagram keeps its source."
            )
