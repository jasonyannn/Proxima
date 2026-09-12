import streamlit as st
from datetime import datetime

try:
    from .agent import ProximaAgent
    from .database import DatabaseManager
    from .prompt import SYSTEM_PROMPT
    from .competitors import CompetitorAnalyzer, STATUS_MATCH, STATUS_PARTIAL
    from .copyright_analyzer import CopyrightAnalyzer, DISCLAIMER
    from .seed_data import seed
except ImportError:  # pragma: no cover
    from agent import ProximaAgent
    from database import DatabaseManager
    from prompt import SYSTEM_PROMPT
    from competitors import CompetitorAnalyzer, STATUS_MATCH, STATUS_PARTIAL
    from copyright_analyzer import CopyrightAnalyzer, DISCLAIMER
    from seed_data import seed


st.set_page_config(
    page_title="Proxima PM Agent",
    page_icon="🤖",
    layout="wide",
)


@st.cache_resource
def get_database() -> DatabaseManager:
    db = DatabaseManager()
    db.init_db()
    return db


def get_agent() -> ProximaAgent:
    return ProximaAgent(database=get_database(), system_prompt=SYSTEM_PROMPT)


db = get_database()
competitor_analyzer = CompetitorAnalyzer(db)
ip_analyzer = CopyrightAnalyzer(db)

STATUS_ICON = {STATUS_MATCH: "✅", STATUS_PARTIAL: "🟡", "Gap": "❌"}
RISK_COLOR = {"Low": "🟢", "Moderate": "🟡", "Elevated": "🟠", "High": "🔴"}
THREAT_COLOR = {"Low": "🟢", "Moderate": "🟡", "High": "🔴"}

# Initialize session state
if "chats" not in st.session_state:
    st.session_state.chats = {}

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = None

# Sidebar for chat management
with st.sidebar:
    st.title("💬 Chats")

    if st.button("➕ New Chat", use_container_width=True):
        new_chat_id = f"chat_{len(st.session_state.chats)}_{datetime.now().timestamp()}"
        st.session_state.chats[new_chat_id] = {"messages": [], "created": datetime.now()}
        st.session_state.current_chat_id = new_chat_id
        st.rerun()

    st.divider()

    # List all chats
    if st.session_state.chats:
        for chat_id, chat_data in st.session_state.chats.items():
            chat_preview = f"Chat {list(st.session_state.chats.keys()).index(chat_id) + 1}"
            if chat_data["messages"]:
                first_msg = chat_data["messages"][0].get("user", "")[:30]
                chat_preview = first_msg + "..." if len(first_msg) > 25 else first_msg

            if st.button(chat_preview, use_container_width=True, key=f"select_{chat_id}"):
                st.session_state.current_chat_id = chat_id
                st.rerun()
    else:
        st.info("No chats yet. Create a new one to get started!")

    st.divider()
    st.caption("Workspace")
    st.caption(
        f"{len(db.list_features())} features · "
        f"{len(db.list_competitors())} competitors · "
        f"{len(db.list_competitor_features())} rival features"
    )
    if st.button("Load sample competitors", use_container_width=True):
        counts = seed(db)
        st.success(
            f"Loaded {counts['competitors']} competitors, "
            f"{counts['competitor_features']} rival features."
        )
        st.rerun()

st.title("🤖 PRODUCT MANAGEMENT AGENT")
st.caption("Turn customer feedback into structured product decisions.")

chat_tab, compare_tab, ip_tab = st.tabs(
    ["💬 Chat", "📊 Competitor Comparison", "⚖️ Copyright Analyser"]
)


# ---------------------------------------------------------------- Chat tab
with chat_tab:
    # Create first chat if none exist
    if not st.session_state.chats:
        new_chat_id = f"chat_0_{datetime.now().timestamp()}"
        st.session_state.chats[new_chat_id] = {"messages": [], "created": datetime.now()}
        st.session_state.current_chat_id = new_chat_id

    current_chat = st.session_state.chats.get(st.session_state.current_chat_id, {})
    messages = current_chat.get("messages", [])

    if messages:
        st.subheader("Conversation")
        for item in messages:
            with st.chat_message("user"):
                st.markdown(item["user"])
            with st.chat_message("assistant"):
                st.markdown(item["agent"])
    else:
        st.info("Start a conversation! Try: 'We've had 20 customers asking for dark mode.'")

    st.divider()
    col1, col2 = st.columns([5, 1])

    with col1:
        user_input = st.text_input(
            "Message Proxima...",
            placeholder="Customers keep asking for dark mode...",
            key="user_input",
        )

    with col2:
        send_button = st.button("Send", use_container_width=True)

    if send_button and user_input.strip():
        agent = get_agent()

        with st.spinner("Proxima is thinking..."):
            response = agent.generate_response(user_input, conversation_history=messages)

        if st.session_state.current_chat_id in st.session_state.chats:
            st.session_state.chats[st.session_state.current_chat_id]["messages"].append(
                {"user": user_input, "agent": response}
            )

        st.rerun()

    with st.expander("📝 Example prompts"):
        st.code(
            "We've had 20 customers asking for dark mode.\n"
            "Users keep reporting sign-out fails after refresh.\n"
            "Customer feedback: 'The checkout flow feels confusing and slow.'\n"
            "Should we prioritize the payment flow over the onboarding?",
            language="text",
        )


# ------------------------------------------------- Competitor comparison tab
with compare_tab:
    st.subheader("Where you stand against the competition")
    st.caption(
        "Matches your shipped features against each competitor's, then shows the "
        "gaps you need to close and the ground you own."
    )

    competitors = db.list_competitors()
    our_features = db.list_features()

    if not competitors:
        st.warning(
            "No competitors yet. Add one below, or click **Load sample competitors** "
            "in the sidebar to see how this works."
        )
    if not our_features:
        st.warning(
            "No features of your own yet. Talk to the agent in the Chat tab, or load "
            "the sample workspace from the sidebar."
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
            cols = st.columns(len(scores)) if scores else []
            for col, score in zip(cols, scores):
                with col:
                    st.metric(
                        f"{THREAT_COLOR[score.threat]} {score.name}",
                        f"{int(score.overlap * 100)}% overlap",
                        f"{len(score.their_advantage)} unanswered",
                        delta_color="inverse",
                    )
                    st.caption(f"Threat: {score.threat}")

            st.divider()

            # --- coverage matrix
            st.markdown("#### Feature coverage matrix")
            matrix = competitor_analyzer.build_matrix(our_features, selected)
            table = []
            for row in matrix:
                entry = {"Your feature": row.feature}
                for name in selected:
                    cell = row.per_competitor[name]
                    icon = STATUS_ICON[cell["status"]]
                    if cell["matched_feature"] and cell["status"] != "Gap":
                        entry[name] = f"{icon} {cell['matched_feature']}"
                    else:
                        entry[name] = f"{icon} —"
                table.append(entry)
            st.dataframe(table, use_container_width=True, hide_index=True)
            st.caption("✅ they have it · 🟡 partial equivalent · ❌ you're alone here")

            st.divider()

            # --- gaps and differentiators
            left, right = st.columns(2)

            with left:
                st.markdown("#### ❌ Gaps to close")
                if gaps["we_are_missing"]:
                    for gap in gaps["we_are_missing"]:
                        with st.expander(f"**{gap['feature']}** — {gap['pressure']}"):
                            st.write(gap["description"] or "_No description on file._")
                            st.caption("Shipped by: " + ", ".join(gap["competitors"]))
                else:
                    st.success("No gaps found against the selected competitors.")

            with right:
                st.markdown("#### ⭐ Your differentiators")
                if gaps["our_differentiators"]:
                    for item in gaps["our_differentiators"]:
                        with st.expander(f"**{item['feature']}**"):
                            st.write(item["description"] or "_No description on file._")
                            st.caption("No selected competitor has a strong equivalent.")
                else:
                    st.info("Nothing unique against this set — everything is at parity.")

            st.divider()

            # --- LLM narrative
            if st.button("🧠 Ask Proxima for a strategic read"):
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
    with st.expander("➕ Manage competitors"):
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


# --------------------------------------------------- Copyright analyser tab
with ip_tab:
    st.subheader("Copyright & IP risk check")
    st.caption(
        "Checks a feature you're about to build against competitor material in this "
        "workspace, separating the idea from the way it's expressed."
    )
    st.info(DISCLAIMER, icon="⚖️")

    rival_features = db.list_competitor_features()
    if not rival_features:
        st.warning(
            "No competitor features loaded yet — the analyser has nothing to compare "
            "against. Load the sample set from the sidebar or add competitors in the "
            "Competitor Comparison tab."
        )

    with st.form("ip_check"):
        proposed_title = st.text_input(
            "Feature name", placeholder="Smart feedback digest"
        )
        proposed_desc = st.text_area(
            "Feature description / spec",
            height=140,
            placeholder=(
                "Describe what you plan to build, in the words you'd put in the spec. "
                "The more detail, the better the wording analysis."
            ),
        )
        run_ip = st.form_submit_button("Analyse risk")

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
                f"{RISK_COLOR[report.risk_level]} {report.risk_level}",
                f"{report.risk_score}/100",
                delta_color="off",
            )
        with head_right:
            st.progress(min(report.risk_score / 100, 1.0))
            st.caption(
                "Score is driven mainly by **wording** overlap, not by building the "
                "same kind of feature — copyright protects expression, not ideas."
            )

        st.divider()
        st.markdown("#### Closest competitor features")
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
        st.markdown("#### Findings")
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
        st.markdown("#### Recommended actions")
        for recommendation in report.recommendations:
            st.markdown(f"- {recommendation}")

        db.create_ip_assessment(
            feature_title=report.feature_title,
            feature_description=report.feature_description,
            risk_level=report.risk_level,
            risk_score=report.risk_score,
            report=report.to_json(),
        )

        if st.button("🧠 Ask Proxima to explain this in plain language"):
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
        with st.expander(f"🗂 Assessment history ({len(past)})"):
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
