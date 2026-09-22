# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Copyright analyser tab.

Copyright and IP risk, for one feature or for the whole workspace.
"""

from __future__ import annotations

from collections import Counter

import streamlit as st

try:
    from .. import theme
    from ..copyright_analyzer import (
        CopyrightSweep,
        DISCLAIMER,
        sweep_from_json,
        sweep_to_json,
    )
    from .constants import RISK_COLOR, RISK_TONE, STATUS_DOT
except ImportError:  # pragma: no cover
    import theme
    from copyright_analyzer import (
        CopyrightSweep,
        DISCLAIMER,
        sweep_from_json,
        sweep_to_json,
    )
    from tabs.constants import RISK_COLOR, RISK_TONE, STATUS_DOT


def render(*, db, get_agent, ip_analyzer, messages):
    """Draw the Copyright analyser tab."""
    theme.section(
        "Copyright & IP risk check",
        note=(
            "Checks a feature you're about to build against competitor material in this "
            "workspace, separating the idea from the way it's expressed."
        ),
        index="01",
    )
    st.info(DISCLAIMER, icon="⚖️")

    rival_features = db.list_competitor_features()
    if not rival_features:
        st.warning(
            "No competitor features loaded yet — the analyser has nothing to compare "
            "against. Add competitors in the Competitor Comparison tab — scanning "
            "the chat there fills in their feature lists too."
        )

    # --- the sweep: everything we build, against everyone we know about
    own_filed = db.list_features()

    sweep_col, _ = st.columns([2, 3])
    if sweep_col.button(
        "Scan everything",
        type="primary",
        use_container_width=True,
        disabled=not rival_features,
        help="Checks every feature you have — filed, plus any this chat describes — against every competitor.",
    ):
        with st.spinner("Reading this chat for features…"):
            profile = st.session_state.get("chat_profile") or (
                get_agent().profile_product(messages) if messages else {}
            )
        filed_titles = {f["title"].lower() for f in own_filed}
        from_chat = [
            {"title": f["title"], "description": f.get("description", ""), "source": "chat"}
            for f in profile.get("features", [])
            if f["title"].lower() not in filed_titles
        ]
        everything = [dict(f, source="filed") for f in own_filed] + from_chat

        if not everything:
            st.session_state.save_toast = "No features to check yet."
        else:
            with st.spinner(f"Checking {len(everything)} features against every competitor…"):
                st.session_state.ip_sweep = {
                    "rows": CopyrightSweep(ip_analyzer).run(everything, rival_features),
                    "competitors": sorted({f["competitor_name"] for f in rival_features}),
                    "from_chat": [f["title"] for f in from_chat],
                }
            # A sweep is minutes of work over the whole workspace. Keeping it
            # only in session state meant a refresh, or a trip to another chat
            # and back, silently threw it away and asked for it again.
            db.save_ip_sweep(
                sweep_to_json(
                    st.session_state.ip_sweep["rows"],
                    st.session_state.ip_sweep["competitors"],
                    st.session_state.ip_sweep["from_chat"],
                )
            )
        st.rerun()

    sweep = st.session_state.get("ip_sweep")
    if not sweep:
        # Nothing in this session yet — read back the last one for this
        # workspace. Unreadable or absent simply means no sweep to show.
        stored = db.load_ip_sweep()
        if stored:
            sweep = sweep_from_json(stored["payload"])
            if sweep:
                sweep["ran_at"] = stored.get("created_at")
                st.session_state.ip_sweep = sweep
            else:
                db.clear_ip_sweep()
    if sweep and sweep["rows"]:
        rows = sweep["rows"]
        hottest = rows[0]
        counts = Counter(row.worst_level for row in rows)

        theme.pills(
            [(f"{len(rows)} features checked", "accent")]
            + [
                (f"{counts[level]} {level.lower()}", tone)
                for level, tone in [
                    ("High", "danger"),
                    ("Elevated", "warn"),
                    ("Moderate", "warn"),
                    ("Low", "ok"),
                ]
                if counts.get(level)
            ]
            + ([(f"{len(sweep['from_chat'])} read from chat", "")] if sweep["from_chat"] else [])
        )

        # A kept result should say it is kept, or the reader cannot tell whether
        # it reflects the features they added since.
        if sweep.get("ran_at"):
            st.caption(
                f"Saved scan from {sweep['ran_at']} — press **Scan everything** "
                "to run it again against the current workspace."
            )

        if hottest.worst_score >= 50:
            st.warning(
                f"**{hottest.feature_title}** is the closest thing you have to "
                f"{hottest.worst_competitor}'s work "
                f"({int(round(hottest.worst_score))}%). Expand it below for what drives that.",
                icon="⚖️",
            )

        theme.risk_matrix(rows, sweep["competitors"])
        st.caption(
            "Each cell: how close that feature of yours reads to that competitor's "
            "nearest equivalent, and which one. Wording similarity — an idea you "
            "share with a rival is not itself infringement."
        )

        st.divider()
        theme.section("What drives each score", index="02")
        for row in rows:
            with st.expander(
                f"**{row.feature_title}** — {int(round(row.worst_score))}% "
                f"{row.worst_level}"
                + (f" · closest to {row.worst_competitor}" if row.worst_competitor else "")
            ):
                report = row.report
                if report and report.matches:
                    st.markdown("**Closest competitor features**")
                    for match in report.matches[:4]:
                        st.markdown(
                            f"- **{match.competitor} / {match.feature}** — {match.relationship}"
                            + (f" · verbatim: “{match.verbatim}”" if match.verbatim else "")
                        )
                if report and report.findings:
                    st.markdown("**Findings**")
                    for finding in report.findings[:5]:
                        st.markdown(
                            f"- {STATUS_DOT.get(finding.severity, '•')} "
                            f"_{finding.kind}_ — {finding.detail}"
                        )
                if report and report.recommendations:
                    st.markdown("**What to do**")
                    for tip in report.recommendations:
                        st.markdown(f"- {tip}")

        if st.button("Clear results", key="clear_sweep"):
            st.session_state.pop("ip_sweep", None)
            db.clear_ip_sweep()
            st.rerun()

        st.divider()

    theme.section("Check one feature", index="03")

    # Same way in as the other tabs: read the chat rather than retype the spec.
    scan_ip, pick_ip, _ = st.columns([2, 2, 3])

    if scan_ip.button(
        "Scan this chat",
        use_container_width=True,
        disabled=not messages,
        help="Takes what you described building and fills the form in.",
    ):
        with st.spinner("Reading the conversation…"):
            profile = st.session_state.get("chat_profile") or get_agent().profile_product(messages)
        first = (profile.get("features") or [{}])[0]
        st.session_state.ip_title = first.get("title") or ""
        st.session_state.ip_desc = (
            first.get("description") or profile.get("summary") or ""
        )
        if not st.session_state.ip_title:
            st.session_state.save_toast = "Nothing in this chat describes a feature yet."
        st.rerun()

    # Or check one already filed, without retyping it.
    own_features = own_filed
    if own_features:
        chosen = pick_ip.selectbox(
            "Check a filed feature",
            options=["—"] + [f["title"] for f in own_features],
            label_visibility="collapsed",
        )
        if chosen != "—":
            picked = next(f for f in own_features if f["title"] == chosen)
            if st.session_state.get("ip_picked") != chosen:
                st.session_state.ip_picked = chosen
                st.session_state.ip_title = picked["title"]
                st.session_state.ip_desc = picked.get("description") or ""
                st.rerun()

    with st.form("ip_check"):
        proposed_title = st.text_input(
            "Feature name",
            placeholder="Smart feedback digest",
            key="ip_title",
        )
        proposed_desc = st.text_area(
            "Feature description / spec",
            height=140,
            placeholder=(
                "Describe what you plan to build, in the words you'd put in the spec. "
                "The more detail, the better the wording analysis."
            ),
            key="ip_desc",
        )
        run_ip = st.form_submit_button("Analyse risk", type="primary")

    if run_ip and proposed_title.strip():
        report = ip_analyzer.analyze(
            feature_title=proposed_title.strip(),
            feature_description=proposed_desc.strip(),
            competitor_features=rival_features,
        )

        head_left, head_right = st.columns([1, 2])
        with head_left:
            st.metric(
                "Risk level",
                report.risk_level,
                f"{report.risk_score}/100",
                delta_color="off",
            )
            theme.pills([(report.risk_level, RISK_TONE[report.risk_level])])
        with head_right:
            st.progress(min(report.risk_score / 100, 1.0))
            st.caption(
                "Score is driven mainly by **wording** overlap, not by building the "
                "same kind of feature — copyright protects expression, not ideas."
            )

        st.divider()
        theme.section("Closest competitor features", index="02")
        if report.matches:
            st.dataframe(
                [
                    {
                        "Competitor": m.competitor,
                        "Their feature": m.feature,
                        "Relationship": m.relationship,
                        "Same idea": f"{int(m.concept * 100)}%",
                        "Same wording": f"{int(m.expression * 100)}%",
                        "Name overlap": f"{int(m.name * 100)}%",
                    }
                    for m in report.matches
                ],
                use_container_width=True,
                hide_index=True,
            )
            for match in report.matches:
                if match.verbatim:
                    st.caption(
                        f"Shared phrasing with {match.competitor}: “{match.verbatim}”"
                    )
        else:
            st.success("Nothing in the workspace resembles this feature.")

        st.divider()
        theme.section("Findings", index="03")
        for finding in report.findings:
            icon = {
                "High": "🔴",
                "Moderate": "🟠",
                "Low": "🟡",
                "Info": "🟢",
            }[finding.severity]
            label = f"{icon} **{finding.severity}** · {finding.kind}"
            if finding.competitor:
                label += f" · {finding.competitor}"
            with st.expander(label, expanded=finding.severity == "High"):
                st.write(finding.detail)
                if finding.evidence:
                    st.code(finding.evidence, language="text")

        st.divider()
        theme.section("Recommended actions", index="04")
        for recommendation in report.recommendations:
            st.markdown(f"- {recommendation}")

        db.create_ip_assessment(
            feature_title=report.feature_title,
            feature_description=report.feature_description,
            risk_level=report.risk_level,
            risk_score=report.risk_score,
            report=report.to_json(),
        )

        if st.button("Ask Proxima to explain this in plain language", type="primary"):
            agent = get_agent()
            with st.spinner("Writing up..."):
                narrative = agent.generate_response(
                    "Explain this IP risk assessment to a product manager who is not a "
                    "lawyer. Say plainly what is safe to build and what needs changing. "
                    "Do not give legal advice; recommend counsel where appropriate.\n\n"
                    + ip_analyzer.briefing(report)
                )
            st.markdown(narrative)

    past = db.list_ip_assessments()
    if past:
        with st.expander(f"Assessment history ({len(past)})"):
            st.dataframe(
                [
                    {
                        "Feature": row["feature_title"],
                        "Risk": f"{RISK_COLOR.get(row['risk_level'], '')} {row['risk_level']}",
                        "Score": row["risk_score"],
                        "When": row["created_at"],
                    }
                    for row in past
                ],
                use_container_width=True,
                hide_index=True,
            )
