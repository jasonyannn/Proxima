import streamlit as st
import requests
import hashlib
from datetime import datetime

try:
    from .agent import ProximaAgent, detect_saveable
    from .database import DatabaseManager
    from .prompt import SYSTEM_PROMPT
    from .competitors import CompetitorAnalyzer, STATUS_MATCH, STATUS_PARTIAL
    from .copyright_analyzer import CopyrightAnalyzer, DISCLAIMER
    from .seed_data import seed
    from . import seed_data
    from . import theme, voice
except ImportError:  # pragma: no cover
    from agent import ProximaAgent, detect_saveable
    from database import DatabaseManager
    from prompt import SYSTEM_PROMPT
    from competitors import CompetitorAnalyzer, STATUS_MATCH, STATUS_PARTIAL
    from copyright_analyzer import CopyrightAnalyzer, DISCLAIMER
    from seed_data import seed
    import seed_data
    import theme, voice


OLLAMA_HOST = "http://localhost:11434"

st.set_page_config(
    page_title="Proxima PM Agent",
    page_icon="🤖",
    layout="wide",
)

theme.inject()


@st.cache_resource
def get_database() -> DatabaseManager:
    db = DatabaseManager()
    db.init_db()
    return db


def get_agent() -> ProximaAgent:
    return ProximaAgent(
        database=get_database(),
        # Rebuilt per call so a settings change takes effect on the next message.
        system_prompt=tuned_system_prompt(),
        ollama_host=OLLAMA_HOST,
    )


@st.cache_data(ttl=20, show_spinner=False)
def llm_online() -> bool:
    """Is the local model server up? Drives the status light in the masthead.

    Cached briefly so a rerun does not fire a request per widget interaction.
    """
    try:
        requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1.5).raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


db = get_database()
competitor_analyzer = CompetitorAnalyzer(db)
ip_analyzer = CopyrightAnalyzer(db)

STATUS_ICON = {STATUS_MATCH: "✅", STATUS_PARTIAL: "🟡", "Gap": "❌"}
RISK_COLOR = {"Low": "🟢", "Moderate": "🟡", "Elevated": "🟠", "High": "🔴"}
THREAT_COLOR = {"Low": "🟢", "Moderate": "🟡", "High": "🔴"}
# Threat and risk levels map onto the pill tones in the theme.
RISK_TONE = {"Low": "ok", "Moderate": "warn", "Elevated": "warn", "High": "danger"}

def chat_title(chat_id: str) -> str:
    """Display name for a chat: an explicit title, else its opening line."""
    chat = st.session_state.chats[chat_id]
    if chat.get("title"):
        return chat["title"]
    if chat["messages"]:
        opening = chat["messages"][0].get("user", "").strip()
        if opening:
            return opening[:28] + "…" if len(opening) > 28 else opening
    return f"Chat {chat.get('ordinal', 1):02d}"


def new_chat() -> str:
    """Start a chat and make it current."""
    st.session_state.chat_counter = st.session_state.get("chat_counter", 0) + 1
    chat_id = f"chat_{st.session_state.chat_counter}_{datetime.now().timestamp()}"
    st.session_state.chats[chat_id] = {
        "messages": [],
        "created": datetime.now(),
        "title": "",
        # Fixed at creation so deleting a chat never renumbers the others.
        "ordinal": st.session_state.chat_counter,
    }
    st.session_state.current_chat_id = chat_id
    return chat_id


def delete_chat(chat_id: str) -> None:
    """Remove a chat, moving the selection to whatever is left."""
    st.session_state.chats.pop(chat_id, None)
    if st.session_state.current_chat_id == chat_id:
        # next() on an empty dict returns None, which the Chat tab treats as
        # "no session" and replaces with a fresh one.
        st.session_state.current_chat_id = next(iter(st.session_state.chats), None)


def submit_message() -> None:
    """Queue whatever is in the box as an unanswered exchange.

    Runs as a widget callback — from Enter in the text box or from the Send
    button — so it fires before the script reruns, and the question is on
    screen from that very pass. The reply is generated further down, once the
    page is painted.
    """
    text = st.session_state.get("user_input", "").strip()
    st.session_state.user_input = ""
    if not text:
        return

    chat = st.session_state.chats.get(st.session_state.current_chat_id)
    if chat is None:
        return

    # Worked out here, with the message: the save chips are on screen straight
    # away, so the user can file a competitor while the answer is still coming.
    known = {c["name"] for c in get_database().list_competitors()}
    chat["messages"].append(
        {
            "user": text,
            "agent": None,
            "suggestions": detect_saveable(text, get_agent(), known),
            "saved": [],
        }
    )


LEVELS = ["High", "Medium", "Low"]
FEATURE_STATUSES = ["Backlog", "Planned", "In Progress", "Shipped"]
BUG_STATUSES = ["Open", "In Progress", "Closed"]
SENTIMENTS = ["positive", "neutral", "negative"]


def _level_index(value: str) -> int:
    """Position of a High/Medium/Low value, defaulting to Medium."""
    value = str(value or "").title()
    return LEVELS.index(value) if value in LEVELS else 1


def render_save_actions(item: dict, index: int) -> None:
    """Offer what a message mentioned as a one-click save.

    This is the only route into product memory: the agent answers, and filing
    anything is the user's decision, taken here.
    """
    saved = item.get("saved", [])
    pending_suggestions = [
        s for s in item.get("suggestions", []) if s["label"] not in saved
    ]

    if saved:
        st.caption(
            "  ".join(
                f"✓ Saved {label.split(':', 1)[1] or 'entry'} → {label.split(':', 1)[0].title()}s"
                for label in saved
            )
        )

    if not pending_suggestions:
        return

    base = f"{st.session_state.current_chat_id}_{index}"
    # Leave the trailing space empty so two chips do not stretch across the page.
    widths = [1] * len(pending_suggestions) + [max(1, 4 - len(pending_suggestions))]

    for column, suggestion in zip(st.columns(widths), pending_suggestions):
        kind = suggestion["kind"]
        key = f"save_{base}_{suggestion['label']}"
        with column:
            if kind == "competitor":
                _competitor_chip(item, suggestion, key)
            elif kind == "feature":
                _feature_chip(item, suggestion, key)
            elif kind == "bug":
                _bug_chip(item, suggestion, key)
            else:
                _feedback_chip(item, suggestion, key)


def _confirm_saved(item: dict, suggestion: dict, message: str) -> None:
    item.setdefault("saved", []).append(suggestion["label"])
    st.session_state.save_toast = message
    st.rerun()


def _competitor_chip(item: dict, suggestion: dict, key: str) -> None:
    with st.popover(f"＋ Competitor: {suggestion['name']}", use_container_width=True):
        st.caption("Mentioned as a rival. Save it to the Competitors tab.")
        name = st.text_input("Name", value=suggestion["name"], key=f"{key}_name")
        website = st.text_input("Website", key=f"{key}_site")
        positioning = st.text_area("Positioning", height=70, key=f"{key}_pos")
        if st.button("Save competitor", key=f"{key}_go", type="primary") and name.strip():
            db.upsert_competitor(
                name=name.strip(),
                website=website.strip() or None,
                positioning=positioning.strip() or None,
            )
            _confirm_saved(item, suggestion, f"{name.strip()} saved to Competitors.")


def _feature_chip(item: dict, suggestion: dict, key: str) -> None:
    with st.popover("＋ Save as feature", use_container_width=True):
        st.caption("Check the title before filing — it is read off your message.")
        title = st.text_input("Title", value=suggestion.get("title", ""), key=f"{key}_title")
        description = st.text_area(
            "Description", value=suggestion.get("description", ""), height=80, key=f"{key}_desc"
        )
        left, mid, right = st.columns(3)
        priority = left.selectbox(
            "Priority", LEVELS, index=_level_index(suggestion.get("priority")), key=f"{key}_pri"
        )
        impact = mid.selectbox(
            "Impact", LEVELS, index=_level_index(suggestion.get("impact")), key=f"{key}_imp"
        )
        effort = right.selectbox(
            "Effort", LEVELS, index=_level_index(suggestion.get("effort")), key=f"{key}_eff"
        )
        status = st.selectbox("Status", FEATURE_STATUSES, key=f"{key}_status")
        if st.button("Save feature", key=f"{key}_go", type="primary") and title.strip():
            db.create_feature(
                title=title.strip(),
                description=description.strip() or None,
                priority=priority,
                impact=impact,
                effort=effort,
                status=status,
            )
            _confirm_saved(item, suggestion, f"“{title.strip()}” saved to Features.")


def _bug_chip(item: dict, suggestion: dict, key: str) -> None:
    with st.popover("＋ Save as bug", use_container_width=True):
        title = st.text_input("Title", value=suggestion.get("title", ""), key=f"{key}_title")
        description = st.text_area(
            "Description", value=suggestion.get("description", ""), height=80, key=f"{key}_desc"
        )
        left, right = st.columns(2)
        severity = left.selectbox(
            "Severity", LEVELS, index=_level_index(suggestion.get("severity")), key=f"{key}_sev"
        )
        status = right.selectbox("Status", BUG_STATUSES, key=f"{key}_status")
        if st.button("Save bug", key=f"{key}_go", type="primary") and title.strip():
            db.create_bug(
                title=title.strip(),
                description=description.strip() or None,
                severity=severity,
                status=status,
            )
            _confirm_saved(item, suggestion, f"“{title.strip()}” saved to Bugs.")


def _feedback_chip(item: dict, suggestion: dict, key: str) -> None:
    with st.popover("＋ Save as feedback", use_container_width=True):
        source = st.text_input("Source", value=suggestion.get("source", "customer"), key=f"{key}_src")
        content = st.text_area(
            "Content", value=suggestion.get("content", ""), height=80, key=f"{key}_content"
        )
        sentiment = st.selectbox(
            "Sentiment",
            SENTIMENTS,
            index=SENTIMENTS.index(suggestion.get("sentiment", "neutral")),
            key=f"{key}_sent",
        )
        if st.button("Save feedback", key=f"{key}_go", type="primary") and content.strip():
            db.create_feedback(
                source=source.strip() or None, content=content.strip(), sentiment=sentiment
            )
            _confirm_saved(item, suggestion, "Feedback saved.")


# Languages the agent can be told to answer in. Ollama's llama3.2 handles these
# to varying degrees; the instruction is advisory, not a guarantee.
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


def recall_digest(limit: int = 6) -> str:
    """Condense earlier sessions into a short block for the system prompt.

    Only the other chats — the active one is already passed as conversation
    history — and only the most recent exchanges, so the prompt stays small.
    """
    lines = []
    for chat_id, chat in reversed(list(st.session_state.chats.items())):
        if chat_id == st.session_state.current_chat_id:
            continue
        for exchange in chat["messages"][-2:]:
            asked = exchange.get("user", "").strip().replace("\n", " ")
            # An exchange still waiting on its reply carries agent=None.
            replied = (exchange.get("agent") or "").strip().replace("\n", " ")
            if asked:
                lines.append(f"- They said: {asked[:160]} | You answered: {replied[:160]}")
        if len(lines) >= limit:
            break
    return "\n".join(lines[:limit])


def tuned_system_prompt() -> str:
    """SYSTEM_PROMPT plus whatever the settings panel asks for."""
    blocks = [SYSTEM_PROMPT]

    language = st.session_state.get("setting_language", "English")
    if language != "English":
        blocks.append(
            f"Always write your replies in {language}, even when the user writes "
            "to you in another language. Keep product terminology accurate."
        )

    if st.session_state.get("setting_recall"):
        digest = recall_digest()
        if digest:
            blocks.append(
                "Context from this user's earlier sessions — use it to stay "
                "consistent, and do not repeat advice you have already given:\n"
                + digest
            )

    return "\n\n".join(blocks)


def capture_speech():
    """Mic control. Returns a transcript the first time a clip is recorded.

    Rendered before the text box so the transcript can be pushed into it: a
    widget's session_state entry cannot be written after the widget exists.
    """
    with st.popover("🎙", use_container_width=True):
        if not voice.backend_available():
            st.caption(
                "Voice input needs a local transcriber. Install it with "
                f"`{voice.INSTALL_HINT}`, then restart the app."
            )
            return None

        st.caption("Record a message — it lands in the box for you to edit.")
        clip = st.audio_input("Speak", key="voice_clip", label_visibility="collapsed")
        if clip is None:
            return None

        # Each rerun hands back the same clip; transcribe a given one only once.
        audio = clip.getvalue()
        digest = hashlib.sha1(audio).hexdigest()
        if st.session_state.get("voice_digest") == digest:
            return None
        st.session_state.voice_digest = digest

        with st.spinner("Transcribing..."):
            return voice.transcribe(audio) or None


# Initialize session state
if "chats" not in st.session_state:
    st.session_state.chats = {}

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = None

# Guarantee exactly one live chat before anything renders: the sidebar lists
# sessions and the Chat tab reads the current one, so neither can be first.
if not st.session_state.chats or st.session_state.current_chat_id is None:
    new_chat()

# Sidebar for chat management
with st.sidebar:
    theme.section("Sessions", index="01")

    if st.button("New chat", use_container_width=True, type="primary"):
        new_chat()
        st.rerun()

    if st.session_state.chats:
        for chat_id in list(st.session_state.chats):
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
                with st.popover("⋮", use_container_width=True, help="Rename or delete"):
                    renamed = st.text_input(
                        "Rename",
                        value=title,
                        key=f"rename_{chat_id}",
                    )
                    if st.button("Save", key=f"save_{chat_id}", use_container_width=True):
                        st.session_state.chats[chat_id]["title"] = renamed.strip()
                        st.rerun()
                    if st.button(
                        "Delete chat",
                        key=f"delete_{chat_id}",
                        use_container_width=True,
                    ):
                        delete_chat(chat_id)
                        st.rerun()
    else:
        st.caption("No sessions yet — start one above.")

    st.divider()
    theme.section("Workspace", index="02")
    theme.pills(
        [
            (f"{len(db.list_features())} features", "accent"),
            (f"{len(db.list_competitors())} competitors", ""),
            (f"{len(db.list_competitor_features())} rival", ""),
        ]
    )
    if st.button("Load demo data", use_container_width=True):
        counts = seed(db)
        st.success(
            f"Loaded {counts['competitors']} demo competitors, "
            f"{counts['competitor_features']} rival features."
        )
        st.rerun()

    if seed_data.loaded_samples(db):
        if st.button("Clear demo data", use_container_width=True):
            removed = seed_data.clear_samples(db)
            st.success(f"Removed {removed} demo competitors.")
            st.rerun()

    st.divider()
    theme.section("Settings", index="03")

    st.selectbox(
        "Reply language",
        options=LANGUAGES,
        key="setting_language",
        help="Proxima answers in this language whatever you type in.",
    )

    st.toggle(
        "Learn from my chats",
        key="setting_recall",
        help="Feeds a short digest of your other sessions into the prompt.",
    )
    st.caption(
        "Passes a summary of your earlier sessions to the agent as context. "
        "It stays on this machine and does not change the model's weights — "
        "this is recall, not training."
    )

theme.hero(
    title="Product Management Agent",
    subtitle="Turn customer feedback into structured product decisions.",
    eyebrow="Proxima // Product intelligence system",
    stats=[
        (len(db.list_features()), "Features"),
        (len(db.list_competitors()), "Competitors"),
        (len(db.list_competitor_features()), "Rival features"),
    ],
    online=llm_online(),
)

chat_tab, memory_tab, compare_tab, ip_tab = st.tabs(
    ["Chat", "Features", "Competitor Comparison", "Copyright Analyser"]
)


# ---------------------------------------------------------------- Chat tab
with chat_tab:
    current_chat = st.session_state.chats.get(st.session_state.current_chat_id, {})
    messages = current_chat.get("messages", [])

    # Set by a save chip on the run before this one.
    toast = st.session_state.pop("save_toast", None)
    if toast:
        st.toast(toast, icon="✅")

    # An exchange with agent=None is one whose question is already on screen but
    # whose reply has not been asked for yet. It keeps a slot in the transcript
    # and is answered at the bottom of the tab, once the page has been painted.
    pending = None

    if messages:
        theme.section("Transcript", index="01")
        for index, item in enumerate(messages):
            with st.chat_message("user"):
                st.markdown(item["user"])
            with st.chat_message("assistant"):
                if item.get("agent") is None:
                    pending = (index, item, st.empty())
                    pending[2].markdown("_Proxima is thinking..._")
                else:
                    st.markdown(item["agent"])

            render_save_actions(item, index)
    else:
        theme.empty_state(
            label="Session ready",
            title="Tell Proxima what your customers are saying",
            body="Paste raw feedback and it comes back as a structured product decision. Try:",
            example="We've had 20 customers asking for dark mode.",
        )

    st.divider()
    input_col, mic_col, send_col = st.columns([5, 1, 1])

    # The mic renders first so a transcript can be written into the text box
    # before that widget is created further down.
    with mic_col:
        spoken = capture_speech()

    if spoken:
        st.session_state.user_input = spoken
        st.rerun()

    with input_col:
        # on_change fires when the box is committed — which is what Enter does.
        st.text_input(
            "Message Proxima",
            placeholder="Customers keep asking for dark mode...",
            key="user_input",
            label_visibility="collapsed",
            on_change=submit_message,
        )

    with send_col:
        st.button(
            "Send",
            use_container_width=True,
            type="primary",
            on_click=submit_message,
        )

    with st.expander("Example prompts"):
        st.code(
            "We've had 20 customers asking for dark mode.\n"
            "Users keep reporting sign-out fails after refresh.\n"
            "Customer feedback: 'The checkout flow feels confusing and slow.'\n"
            "Should we prioritize the payment flow over the onboarding?",
            language="text",
        )

    # Last thing in the tab: the question and the input box are both on screen
    # before the model is called, and the answer lands in the slot held above.
    if pending is not None:
        pending_index, pending_item, slot = pending
        # Streamed into the slot as it is written, so a long analysis reads
        # as progress rather than as a page that has hung.
        written = ""
        painted = 0
        for piece in get_agent().stream_response(
            pending_item["user"], conversation_history=messages[:pending_index]
        ):
            written += piece
            # Repaint every few words, not every token — each update is a
            # message to the browser.
            if len(written) - painted >= 24:
                painted = len(written)
                slot.markdown(written + " ▍")

        pending_item["agent"] = written
        slot.markdown(written)



# ------------------------------------------------------------- Features tab
with memory_tab:
    theme.section(
        "Product memory",
        note=(
            "Everything you have filed from chat. Proxima never writes here on "
            "its own — each entry got here because you saved it."
        ),
        index="01",
    )

    features = db.list_features()
    bugs = db.list_bugs()
    feedback_items = db.list_feedback()

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


# ------------------------------------------------- Competitor comparison tab
with compare_tab:
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

    # Say plainly when the analysis is running on the fictional sample set.
    samples_present = seed_data.loaded_samples(db)
    if samples_present:
        theme.demo_banner([c["name"] for c in samples_present])

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
                        score.name,
                        f"{int(score.overlap * 100)}% overlap",
                        f"{len(score.their_advantage)} unanswered",
                        delta_color="inverse",
                    )
                    tags = [(f"Threat: {score.threat}", RISK_TONE[score.threat])]
                    if score.name in seed_data.SAMPLE_COMPETITOR_NAMES:
                        tags.append(("Demo", "warn"))
                    theme.pills(tags)

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


# --------------------------------------------------- Copyright analyser tab
with ip_tab:
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
