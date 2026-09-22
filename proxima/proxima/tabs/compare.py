# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Competitor comparison tab.

What we have against what they have, feature by feature.
"""

from __future__ import annotations

import streamlit as st

try:
    from .. import theme
    from ..competitors import STATUS_UNKNOWN
    from .constants import RISK_TONE, STATUS_ICON
except ImportError:  # pragma: no cover
    import theme
    from competitors import STATUS_UNKNOWN
    from tabs.constants import RISK_TONE, STATUS_ICON


def render(*, competitor_analyzer, db, get_agent, messages, run_research):
    """Draw the Competitor comparison tab."""
    theme.section(
        "Where you stand",
        note=(
            "Matches your shipped features against each competitor's, then shows the "
            "gaps you need to close and the ground you own."
        ),
        index="01",
    )

    competitors = db.list_competitors()
    our_features = db.list_features()
    known_names = {c["name"] for c in competitors}

    # Three ways in, because they answer different questions: who did I already
    # mention, who else is out there, and the one I happen to know about. The
    # last one is a plain form, and stays that way — it is the only one of the
    # three that is never wrong.
    scan_col, suggest_col, manual_col, _ = st.columns([2, 2, 2, 1])

    with manual_col:
        with st.popover("Add one by hand", use_container_width=True):
            with st.form("quick_competitor", clear_on_submit=True):
                st.caption("Yours to type. Nothing is guessed here.")
                hand_name = st.text_input("Name")
                hand_site = st.text_input("Website")
                hand_pos = st.text_area("Positioning", height=70)
                look_up = st.checkbox(
                    "Also fill in their features", value=True,
                    help="Asks the local model what it knows of their product.",
                )
                if st.form_submit_button("Add competitor", type="primary") and hand_name.strip():
                    db.upsert_competitor(
                        name=hand_name.strip(),
                        website=hand_site.strip() or None,
                        positioning=hand_pos.strip() or None,
                    )
                    if look_up:
                        st.session_state.research_queue = hand_name.strip()
                    st.session_state.save_toast = f"Added {hand_name.strip()}."
                    st.rerun()

    if scan_col.button(
        "Scan this chat for competitors",
        use_container_width=True,
        disabled=not messages,
        help="Reads the whole conversation and files the rivals you named.",
    ):
        with st.spinner("Reading the conversation…"):
            named = get_agent().competitors_in_conversation(messages)
        fresh = [c for c in named if c["name"] not in known_names]
        already = [c["name"] for c in named if c["name"] in known_names]
        st.session_state.rival_proposal = {
            "source": "chat",
            "rows": fresh,
            # Say which of the two nothings this is: nobody was named, or
            # everybody named is already on file.
            "empty": (
                f"Already filed, so nothing to add: {', '.join(already)}."
                if already
                else "No competitor is named in this chat yet. Mention one by "
                "name — \"like Airbnb but for parking\" counts — and scan again."
            ),
        }
        st.rerun()

    if suggest_col.button(
        "Suggest rivals",
        use_container_width=True,
        disabled=not messages,
        help="Names competitors the chat never mentioned, from what your product does.",
    ):
        with st.spinner("Thinking about who else is out there…"):
            profile = st.session_state.get("chat_profile") or get_agent().profile_product(messages)
            summary = profile.get("summary", "")
            rows = get_agent().suggest_rivals(summary, exclude=known_names) if summary else []
        st.session_state.rival_proposal = {
            "source": "model",
            "rows": rows,
            "summary": summary,
            "empty": "Describe your product in the chat first — there is nothing to match against.",
        }
        st.rerun()

    proposal = st.session_state.get("rival_proposal")
    if proposal is not None:
        with st.container(border=True):
            if not proposal["rows"]:
                st.caption(proposal["empty"])
            else:
                if proposal["source"] == "model":
                    st.markdown(
                        "**Not mentioned in this chat** — suggested from "
                        f"_{proposal.get('summary', 'your product')}_. The model is "
                        "going from memory here, so check a name before you trust it."
                    )
                else:
                    st.markdown("**Named in this chat.**")

                picked = []
                for row in proposal["rows"]:
                    label = f"**{row['name']}**"
                    detail = row.get("why") or row.get("positioning") or ""
                    if st.checkbox(
                        f"{label} — {detail}" if detail else label,
                        value=True,
                        key=f"rival_pick_{row['name']}",
                    ):
                        picked.append(row)

                st.caption(
                    "Filing one also fills in what the model knows of its feature "
                    "set, so the comparison below has something to match against."
                )
                go, _ = st.columns([2, 3])
                if go.button(
                    f"File {len(picked)} competitor{'s' if len(picked) != 1 else ''}",
                    type="primary",
                    use_container_width=True,
                    disabled=not picked,
                ):
                    progress = st.progress(0.0, text="Filing…")
                    for index, row in enumerate(picked, start=1):
                        db.upsert_competitor(
                            name=row["name"],
                            positioning=row.get("positioning") or None,
                        )
                        progress.progress(
                            (index - 0.5) / len(picked), text=f"Reading up on {row['name']}…"
                        )
                        run_research(row["name"])
                        progress.progress(index / len(picked), text=f"Filed {row['name']}")
                    st.session_state.pop("rival_proposal", None)
                    st.session_state.save_toast = f"Filed {len(picked)} competitors."
                    st.rerun()

            if st.button("Close", key="rival_close"):
                st.session_state.pop("rival_proposal", None)
                st.rerun()

    if not competitors:
        st.info(
            "No competitors in this chat yet. Name one while you talk to Proxima "
            "and it offers to file them — or scan the chat above."
        )
    if not our_features:
        st.info(
            "No features of your own yet. Describe what you are building in the "
            "Chat tab, then use **Read this chat for features** on the Features tab."
        )

    if competitors and our_features:
        selected = st.multiselect(
            "Compare against",
            options=[c["name"] for c in competitors],
            default=[c["name"] for c in competitors],
        )

        if selected:
            scores = competitor_analyzer.score_competitors(our_features, selected)
            gaps = competitor_analyzer.gap_analysis(our_features, selected)

            # --- headline numbers
            blank = [s.name for s in scores if not s.researched]
            if blank:
                st.warning(
                    "No feature list on file for "
                    + ", ".join(f"**{name}**" for name in blank)
                    + ". They are left out of the percentages below — a rival "
                    "nobody has researched is not the same as a rival with "
                    "nothing. Use **Look them up** to fill them in.",
                    icon="⚠️",
                )
                if st.button(f"Look them up ({len(blank)})", type="primary"):
                    progress = st.progress(0.0, text="Reading up…")
                    for index, name in enumerate(blank, start=1):
                        progress.progress((index - 0.5) / len(blank), text=f"Reading up on {name}…")
                        run_research(name)
                        progress.progress(index / len(blank), text=f"Done: {name}")
                    st.rerun()

            cols = st.columns(len(scores)) if scores else []
            for col, score in zip(cols, scores):
                with col:
                    if not score.researched:
                        st.metric(score.name, "—", "not researched", delta_color="off")
                        theme.pills([("No data", "warn")])
                        continue
                    st.metric(
                        score.name,
                        f"{int(score.overlap * 100)}% overlap",
                        f"{len(score.their_advantage)} unanswered",
                        delta_color="inverse",
                    )
                    theme.pills([(f"Threat: {score.threat}", RISK_TONE[score.threat])])

            st.divider()

            # --- coverage matrix
            theme.section("Feature coverage matrix", index="02")
            matrix = competitor_analyzer.build_matrix(our_features, selected)
            table = []
            for row in matrix:
                entry = {"Your feature": row.feature}
                for name in selected:
                    cell = row.per_competitor[name]
                    icon = STATUS_ICON[cell["status"]]
                    if cell["status"] == STATUS_UNKNOWN:
                        entry[name] = f"{icon} no data"
                    elif cell["matched_feature"] and cell["status"] != "Gap":
                        entry[name] = f"{icon} {cell['matched_feature']}"
                    else:
                        entry[name] = f"{icon} —"
                table.append(entry)
            st.dataframe(table, use_container_width=True, hide_index=True)
            st.caption(
                "✅ they have it · 🟡 partial equivalent · ❌ you're alone here · "
                "· nothing on file for them, so nothing is claimed"
            )

            st.divider()

            # --- gaps and differentiators
            left, right = st.columns(2)

            with left:
                theme.section("Gaps to close", index="03")
                if gaps["we_are_missing"]:
                    for gap in gaps["we_are_missing"]:
                        with st.expander(f"**{gap['feature']}** — {gap['pressure']}"):
                            st.write(gap["description"] or "_No description on file._")
                            st.caption("Shipped by: " + ", ".join(gap["competitors"]))
                else:
                    st.success("No gaps found against the selected competitors.")

            with right:
                theme.section("Your differentiators", index="04")
                if gaps["our_differentiators"]:
                    for item in gaps["our_differentiators"]:
                        with st.expander(f"**{item['feature']}**"):
                            st.write(item["description"] or "_No description on file._")
                            st.caption("No selected competitor has a strong equivalent.")
                else:
                    st.info("Nothing unique against this set — everything is at parity.")

            st.divider()

            # --- LLM narrative
            if st.button("Ask Proxima for a strategic read", type="primary"):
                briefing = competitor_analyzer.summary_prompt(gaps, scores)
                agent = get_agent()
                with st.spinner("Analysing position..."):
                    narrative = agent.generate_response(
                        "Given this competitive analysis, what should we prioritise next "
                        "quarter and why? Be specific and rank your recommendations.\n\n"
                        + briefing
                    )
                st.markdown(narrative)

    st.divider()
    with st.expander("Manage competitors"):
        st.markdown("**Add or update a competitor**")
        with st.form("add_competitor", clear_on_submit=True):
            name = st.text_input("Name")
            website = st.text_input("Website")
            positioning = st.text_area("Positioning", height=70)
            pricing = st.text_input("Pricing")
            if st.form_submit_button("Save competitor") and name.strip():
                db.upsert_competitor(
                    name=name.strip(),
                    website=website.strip() or None,
                    positioning=positioning.strip() or None,
                    pricing=pricing.strip() or None,
                )
                st.success(f"Saved {name}.")
                st.rerun()

        if competitors:
            st.markdown("**Add a feature to a competitor**")
            with st.form("add_competitor_feature", clear_on_submit=True):
                target = st.selectbox(
                    "Competitor", options=[c["name"] for c in competitors]
                )
                feature_name = st.text_input("Feature name")
                feature_desc = st.text_area("Description", height=90)
                category = st.text_input("Category (optional)")
                if st.form_submit_button("Add feature") and feature_name.strip():
                    target_id = next(c["id"] for c in competitors if c["name"] == target)
                    db.create_competitor_feature(
                        competitor_id=target_id,
                        name=feature_name.strip(),
                        description=feature_desc.strip() or None,
                        category=category.strip() or None,
                    )
                    st.success(f"Added '{feature_name}' to {target}.")
                    st.rerun()

            st.markdown("**Remove a competitor**")
            to_remove = st.selectbox(
                "Competitor to delete",
                options=[c["name"] for c in competitors],
                key="remove_competitor",
            )
            if st.button("Delete", type="secondary"):
                target_id = next(c["id"] for c in competitors if c["name"] == to_remove)
                db.delete_competitor(target_id)
                st.success(f"Deleted {to_remove}.")
                st.rerun()
