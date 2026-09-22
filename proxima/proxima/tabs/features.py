# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Features tab.

Everything filed in this workspace, and what the chat implies is missing.
"""

from __future__ import annotations

from collections import Counter

import streamlit as st

try:
    from .. import theme
    from .constants import FEATURE_STATUSES, LEVELS
except ImportError:  # pragma: no cover
    import theme
    from tabs.constants import FEATURE_STATUSES, LEVELS


def render(*, db, file_product_features, get_agent, messages):
    """Draw the Features tab."""
    theme.section(
        "Product memory",
        note=(
            "This chat's product. Every other chat keeps its own — features, "
            "competitors and risk checks belong to the thing being discussed. "
            "Proxima files nothing here on its own."
        ),
        index="01",
    )

    features = db.list_features()
    bugs = db.list_bugs()
    feedback_items = db.list_feedback()

    # Reading the whole conversation catches what message-by-message matching
    # cannot: a product described across four turns and never "requested".
    read_col, hand_col, _ = st.columns([2, 2, 2])

    with hand_col.popover("Add feature", use_container_width=True):
        with st.form("hand_feature", clear_on_submit=True):
            st.caption("Yours to type. Nothing is guessed here.")
            hand_title = st.text_input("Title")
            hand_desc = st.text_area("Description", height=80)
            grade = st.columns(3)
            hand_priority = grade[0].selectbox("Priority", LEVELS, index=1, key="hand_pri")
            hand_impact = grade[1].selectbox("Impact", LEVELS, index=1, key="hand_imp")
            hand_effort = grade[2].selectbox("Effort", LEVELS, index=1, key="hand_eff")
            hand_status = st.selectbox("Status", FEATURE_STATUSES, key="hand_status")
            if st.form_submit_button("Add feature", type="primary") and hand_title.strip():
                db.create_feature(
                    title=hand_title.strip(),
                    description=hand_desc.strip() or None,
                    priority=hand_priority,
                    impact=hand_impact,
                    effort=hand_effort,
                    status=hand_status,
                )
                st.session_state.save_toast = f"Added {hand_title.strip()}."
                st.rerun()

    if messages:
        if read_col.button(
            "Read this chat for features",
            use_container_width=True,
            type="primary" if not features else "secondary",
            help="Goes through the whole conversation and lists what your product does.",
        ):
            with st.spinner("Reading the conversation…"):
                profile = get_agent().profile_product(messages)
            if profile.get("features"):
                st.session_state.chat_profile = profile
            else:
                st.session_state.save_toast = "Nothing in this chat describes a product yet."
                st.rerun()

    proposed = st.session_state.get("chat_profile")
    if proposed:
        with st.container(border=True):
            if proposed.get("summary"):
                st.markdown(f"**Proxima reads this chat as:** {proposed['summary']}")
            st.caption("Filing these puts them in this chat's feature list.")
            for feature in proposed["features"]:
                st.markdown(f"- **{feature['title']}** — {feature.get('description', '')}")
            keep, drop, _ = st.columns([2, 1, 2])
            if keep.button(
                f"File all {len(proposed['features'])}", use_container_width=True, type="primary"
            ):
                added = file_product_features(proposed)
                st.session_state.pop("chat_profile", None)
                st.session_state.save_toast = f"Filed {added} features."
                st.rerun()
            if drop.button("Discard", use_container_width=True):
                st.session_state.pop("chat_profile", None)
                st.rerun()

    theme.pills(
        [
            (f"{len(features)} features", "accent"),
            (f"{len(bugs)} bugs", "warn" if bugs else ""),
            (f"{len(feedback_items)} feedback", ""),
        ]
    )

    if not features and not bugs and not feedback_items:
        theme.empty_state(
            label="Nothing filed yet",
            title="Your backlog starts in the chat",
            body=(
                "Mention a feature, a bug or a rival and Proxima offers to file it "
                "under the message. Nothing is saved until you say so. Try:"
            ),
            example="We've had 20 customers asking for dark mode.",
        )

    # Earlier builds filed a row on every message, so most backlogs start out
    # with a pile of duplicates nobody asked for. Clearing them one by one is
    # not a fair ask.
    duplicates = [
        title for title, count in Counter(f["title"] for f in features).items() if count > 1
    ]
    if duplicates or len(features) > 1:
        with st.popover("Clean up", use_container_width=False):
            if duplicates:
                st.caption(
                    f"{len(duplicates)} title(s) appear more than once. Keeps the "
                    "newest of each and removes the rest."
                )
                if st.button("Remove duplicate features", type="primary"):
                    kept: set[str] = set()
                    removed = 0
                    for feature in features:  # newest first
                        if feature["title"] in kept:
                            db.delete_feature(feature["id"])
                            removed += 1
                        else:
                            kept.add(feature["title"])
                    st.session_state.save_toast = f"Removed {removed} duplicate features."
                    st.rerun()
            st.caption("Or empty the list entirely — this cannot be undone.")
            if st.button(f"Delete all {len(features)} features"):
                for feature in features:
                    db.delete_feature(feature["id"])
                st.session_state.save_toast = f"Deleted {len(features)} features."
                st.rerun()

    if features:
        st.markdown("**Features**")
        for feature in features:
            with st.expander(f"**{feature['title']}** — {feature.get('status', '')}"):
                st.write(feature.get("description") or "_No description on file._")
                theme.pills(
                    [
                        (f"priority {feature.get('priority', '—')}", "accent"),
                        (f"impact {feature.get('impact', '—')}", ""),
                        (f"effort {feature.get('effort', '—')}", ""),
                    ]
                )
                st.caption(f"Filed {feature.get('created_at', 'recently')}")
                if st.button("Remove", key=f"del_feature_{feature['id']}"):
                    db.delete_feature(feature["id"])
                    st.rerun()

    if bugs:
        st.markdown("**Bugs**")
        for bug in bugs:
            with st.expander(f"**{bug['title']}** — {bug.get('status', '')}"):
                st.write(bug.get("description") or "_No description on file._")
                theme.pills([(f"severity {bug.get('severity', '—')}", "danger")])
                st.caption(f"Filed {bug.get('created_at', 'recently')}")
                if st.button("Remove", key=f"del_bug_{bug['id']}"):
                    db.delete_bug(bug["id"])
                    st.rerun()

    if feedback_items:
        st.markdown("**Feedback**")
        for entry in feedback_items:
            label = (entry.get("content") or "")[:60]
            with st.expander(f"**{label}** — {entry.get('sentiment', '')}"):
                st.write(entry.get("content") or "")
                st.caption(
                    f"From {entry.get('source') or 'unknown'} · "
                    f"filed {entry.get('created_at', 'recently')}"
                )
                if st.button("Remove", key=f"del_feedback_{entry['id']}"):
                    db.delete_feedback(entry["id"])
                    st.rerun()
