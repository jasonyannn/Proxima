# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

import streamlit as st
import requests
import hashlib
import html
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    from .agent import ProximaAgent, detect_saveable, suggestions_from_model
    from .database import DatabaseManager
    from .prompt import SYSTEM_PROMPT
    from .competitors import (
        CompetitorAnalyzer,
        STATUS_MATCH,
        STATUS_PARTIAL,
        STATUS_UNKNOWN,
    )
    from .copyright_analyzer import CopyrightAnalyzer, CopyrightSweep, DISCLAIMER
    from .prompt_box import prompt_box
    from .kanban import kanban
    from . import theme, voice, workspace, landing, memory, visuals, accessibility, report
except ImportError:  # pragma: no cover
    from agent import ProximaAgent, detect_saveable, suggestions_from_model
    from database import DatabaseManager
    from prompt import SYSTEM_PROMPT
    from competitors import (
        CompetitorAnalyzer,
        STATUS_MATCH,
        STATUS_PARTIAL,
        STATUS_UNKNOWN,
    )
    from copyright_analyzer import CopyrightAnalyzer, CopyrightSweep, DISCLAIMER
    from prompt_box import prompt_box
    from kanban import kanban
    import theme, voice, workspace, landing, memory, visuals, accessibility, report


OLLAMA_HOST = "http://localhost:11434"

# Brand assets live beside the code, so they resolve wherever the app is run
# from. The mark is the glyph alone on transparency — a browser tab is small,
# and the wordmark is illegible at 16px.
ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = str(ASSETS / "proxima-logo.png")
LOGO_MARK = str(ASSETS / "proxima-mark.png")

st.set_page_config(
    page_title="Proxima PM Agent",
    page_icon=LOGO_MARK,
    layout="wide",
)

# Sidebar lockup, collapsing to the glyph when the sidebar is closed.
st.logo(LOGO, icon_image=LOGO_MARK, size="large")

theme.inject()

# Nothing below this point renders until someone is signed in: chats, and the
# workspaces hanging off them, belong to an account.
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    signed_in = landing.render(LOGO_MARK)
    if signed_in:
        st.session_state.user = signed_in
        st.rerun()
    st.stop()

USER = st.session_state.user


@st.cache_resource
def get_database(chat_id: str, owner: int) -> DatabaseManager:
    """The open chat's own product memory — see workspace.py for why."""
    return workspace.database_for(chat_id, owner)


def current_db() -> DatabaseManager:
    return get_database(st.session_state.current_chat_id, USER["id"])


def get_agent() -> ProximaAgent:
    return ProximaAgent(
        database=current_db(),
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


STATUS_ICON = {STATUS_MATCH: "✅", STATUS_PARTIAL: "🟡", "Gap": "❌", STATUS_UNKNOWN: "·"}
RISK_COLOR = {"Low": "🟢", "Moderate": "🟡", "Elevated": "🟠", "High": "🔴"}
THREAT_COLOR = {"Low": "🟢", "Moderate": "🟡", "High": "🔴"}
# Threat and risk levels map onto the pill tones in the theme.
STATUS_DOT = {"High": "🔴", "Moderate": "🟠", "Low": "🟡", "Info": "🔵"}

RISK_TONE = {
    "Low": "ok",
    "Moderate": "warn",
    "Elevated": "warn",
    "High": "danger",
    "Unknown": "",
}

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


def new_chat(project_id: str | None = None) -> str:
    """Start a chat and make it current.

    With no project named it inherits the open chat's — pressing New chat while
    you are inside a project means another chat about that same product, not a
    stray one that falls out of it.
    """
    if project_id is None:
        current = st.session_state.chats.get(st.session_state.get("current_chat_id"))
        project_id = (current or {}).get("project_id")

    st.session_state.chat_counter = st.session_state.get("chat_counter", 0) + 1
    chat_id = f"chat_{st.session_state.chat_counter}_{datetime.now().timestamp()}"
    st.session_state.chats[chat_id] = {
        "messages": [],
        "created": datetime.now(),
        "title": "",
        # Fixed at creation so deleting a chat never renumbers the others.
        "ordinal": st.session_state.chat_counter,
        "project_id": project_id or None,
    }
    st.session_state.current_chat_id = chat_id
    remember_sessions()
    return chat_id


def delete_chat(chat_id: str) -> None:
    """Remove a chat, its workspace, and everything filed in it."""
    st.session_state.chats.pop(chat_id, None)
    get_database.clear()
    workspace.discard(chat_id, USER["id"])
    if st.session_state.current_chat_id == chat_id:
        # next() on an empty dict returns None, which the Chat tab treats as
        # "no session" and replaces with a fresh one.
        st.session_state.current_chat_id = next(iter(st.session_state.chats), None)
    remember_sessions()


# ---------------------------------------------------------------- projects

def new_project(name: str = "") -> str:
    """Create a project and return its id."""
    st.session_state.project_counter = st.session_state.get("project_counter", 0) + 1
    ordinal = st.session_state.project_counter
    project_id = f"proj_{ordinal}_{datetime.now().timestamp()}"
    st.session_state.projects[project_id] = {
        "name": (name or "").strip() or f"Project {ordinal:02d}",
        "brief": "",
        "created": datetime.now(),
        "ordinal": ordinal,
    }
    remember_sessions()
    return project_id


def delete_project(project_id: str, drop_chats: bool = False) -> None:
    """Remove a project. Its chats are unfiled unless asked for otherwise.

    Deleting a folder should not delete the work inside it by default — the
    chats carry the workspaces, and those hold everything anyone saved.
    """
    st.session_state.projects.pop(project_id, None)
    for chat_id in list(st.session_state.chats):
        if st.session_state.chats[chat_id].get("project_id") != project_id:
            continue
        if drop_chats:
            delete_chat(chat_id)
        else:
            st.session_state.chats[chat_id]["project_id"] = None
    remember_sessions()


def move_chat(chat_id: str, project_id: str | None) -> None:
    """File a chat under a project, or unfile it with None."""
    chat = st.session_state.chats.get(chat_id)
    if chat is None:
        return
    chat["project_id"] = project_id or None
    remember_sessions()


def project_of(chat_id: str | None) -> dict | None:
    """The project a chat belongs to, with its id folded in, or None.

    The id rides along because memory.py keys the recall scope off it and
    should not have to be handed the dict and the id separately.
    """
    chat = st.session_state.chats.get(chat_id or "")
    project_id = (chat or {}).get("project_id")
    project = st.session_state.get("projects", {}).get(project_id or "")
    if not project:
        return None
    return {**project, "id": project_id}


def current_project() -> dict | None:
    return project_of(st.session_state.get("current_chat_id"))


def current_settings() -> dict:
    """The accessibility and answer-style settings, as chosen right now.

    Read back out of the widgets rather than kept in a parallel dict, so there
    is one source of truth and no way for the two to disagree.
    """
    raw = {key: st.session_state.get(f"set_{key}") for key in accessibility.DEFAULTS}
    # The switch is phrased as "never use colour alone", which is the opposite
    # of how the setting is stored — a toggle reads better as the thing you turn
    # on than as the thing you turn off.
    raw["colour_alone"] = not st.session_state.get("set_colour_alone_inverted", False)
    return accessibility.normalise(raw)


def remember_sessions() -> None:
    """Persist the chats, the projects grouping them, and the recall scope.

    A workspace outlives the session that opened it, so the chat it belongs to
    has to outlive it too — and now so does the project it is filed under.
    """
    workspace.save_state(
        st.session_state.get("chats", {}),
        st.session_state.get("chat_counter", 0),
        USER["id"],
        projects=st.session_state.get("projects", {}),
        project_counter=st.session_state.get("project_counter", 0),
        scope=st.session_state.get("setting_memory_scope", workspace.DEFAULT_SCOPE),
        settings=current_settings(),
    )


def handle_prompt_request(request: dict | None) -> None:
    """Answer whatever the input asked for: a correction, a guess, or a send.

    The component raises a request, Streamlit re-runs, and the answer goes back
    as a prop on the next render. Each request carries a nonce so a re-run for
    an unrelated reason does not replay the last one.
    """
    if not isinstance(request, dict):
        return

    nonce = request.get("nonce")
    if not nonce or nonce == st.session_state.get("box_nonce"):
        return
    st.session_state.box_nonce = nonce

    kind = request.get("kind")
    text = str(request.get("text", ""))

    if kind == "submit":
        queue_message(text)
        # Clear the box by bumping the revision the component watches.
        st.session_state.box_text = ""
        st.session_state.box_revision = st.session_state.get("box_revision", 0) + 1
        st.session_state.box_response = None
        st.rerun()

    if kind in {"polish", "predict"}:
        agent = get_agent()
        value = (
            agent.polish_prompt(text)
            if kind == "polish"
            else agent.predict_continuation(text)
        )
        st.session_state.box_response = {"nonce": nonce, "kind": kind, "value": value}
        st.rerun()


def queue_message(text: str) -> None:
    """Record a question with no answer yet, so it appears at once."""
    text = text.strip()
    if not text:
        return

    chat = st.session_state.chats.get(st.session_state.current_chat_id)
    if chat is None:
        return

    # Worked out here, with the message: the save chips are on screen straight
    # away, so the user can file a competitor while the answer is still coming.
    known = {c["name"] for c in current_db().list_competitors()}
    chat["messages"].append(
        {
            "user": text,
            "agent": None,
            "suggestions": detect_saveable(text, get_agent(), known),
            "saved": [],
        }
    )


# Stamped on rival features that came from the model's memory rather than from
# anyone checking the competitor's product.
RECALLED = "model-recall"

LEVELS = ["High", "Medium", "Low"]
FEATURE_STATUSES = ["Backlog", "Planned", "In Progress", "Shipped"]
BUG_STATUSES = ["Open", "In Progress", "Closed"]
SENTIMENTS = ["positive", "neutral", "negative"]


def _level_index(value: str) -> int:
    """Position of a High/Medium/Low value, defaulting to Medium."""
    value = str(value or "").title()
    return LEVELS.index(value) if value in LEVELS else 1


def _shorten(text: str, limit: int = 26) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def chip_label(suggestion: dict) -> str:
    """What the save button says. One press does exactly this."""
    if suggestion["kind"] == "competitor":
        return f"＋ Save {_shorten(suggestion['name'])} as competitor"
    if suggestion["kind"] == "feedback":
        return "＋ Save as feedback"
    return f"＋ Save “{_shorten(suggestion.get('title', ''))}” as {suggestion['kind']}"


def merge_suggestions(existing: list[dict], extra: list[dict]) -> list[dict]:
    """Fold the model's reading into the keyword rules' first guess.

    Where both described the same kind of thing, the model wins. The rules
    build a feature title by slicing the sentence — "You To Analyse Whether
    Building This Could Create Copyright" — and nobody wants that in a backlog.
    Competitor names are left alone: there the rules are exact, and dropping one
    the model happened to miss would lose it.
    """
    replaceable = {"feature", "bug", "feedback"} & {s["kind"] for s in extra}
    kept = [
        s
        for s in existing
        if s.get("source") != "rules" or s["kind"] not in replaceable
    ]
    seen = {s["label"] for s in kept}
    return kept + [s for s in extra if s["label"] not in seen]


def save_suggestion(item: dict, suggestion: dict) -> None:
    """File one suggestion. Runs as a button callback.

    A callback rather than an `if st.button(...)` body because the answer above
    may still be streaming: a callback is applied before the script re-runs, so
    the save lands whether or not the run that was in flight survives.
    """
    kind = suggestion["kind"]

    if kind == "competitor":
        row_id = current_db().upsert_competitor(
            name=suggestion["name"],
            positioning=suggestion.get("positioning") or None,
        )
        what, where = suggestion["name"], "Competitors"
        # A competitor with no features is a name in a list: the comparison has
        # nothing to match against and reports 0% overlap. Ask for what the
        # model knows of their product, so the tab means something on arrival.
        st.session_state.research_queue = suggestion["name"]
    elif kind == "feature":
        row_id = current_db().create_feature(
            title=suggestion["title"],
            description=suggestion.get("description") or None,
            priority=str(suggestion.get("priority", "Medium")).title(),
            impact=str(suggestion.get("impact", "Medium")).title(),
            effort=str(suggestion.get("effort", "Medium")).title(),
            status=str(suggestion.get("status", "Backlog")).title(),
        )
        what, where = suggestion["title"], "Features"
    elif kind == "bug":
        row_id = current_db().create_bug(
            title=suggestion["title"],
            description=suggestion.get("description") or None,
            severity=str(suggestion.get("severity", "Medium")).title(),
            status=str(suggestion.get("status", "Open")).title(),
        )
        what, where = suggestion["title"], "Bugs"
    else:
        row_id = current_db().create_feedback(
            source=suggestion.get("source") or None,
            content=suggestion.get("content", ""),
            sentiment=suggestion.get("sentiment", "neutral"),
        )
        what, where = "Feedback", "Feedback"

    item.setdefault("saved", []).append(
        {"label": suggestion["label"], "kind": kind, "id": row_id, "what": what, "where": where}
    )
    st.session_state.save_toast = f"{_shorten(what, 40)} saved to {where}."


def undo_save(item: dict, entry: dict) -> None:
    """Take back a save. The chip returns, so it can be filed again."""
    remove = {
        "competitor": current_db().delete_competitor,
        "feature": current_db().delete_feature,
        "bug": current_db().delete_bug,
        "feedback": current_db().delete_feedback,
    }[entry["kind"]]
    remove(entry["id"])
    item["saved"] = [e for e in item.get("saved", []) if e["label"] != entry["label"]]
    st.session_state.save_toast = f"Removed {_shorten(entry['what'], 40)}."


def run_research(name: str) -> int:
    """Fill in a competitor's feature list from what the model knows.

    Recalled, not researched — the model has no browser. Every row is marked
    as such where it is shown, and is there to be corrected rather than
    trusted.
    """
    store = current_db()
    competitor = next(
        (c for c in store.list_competitors() if c["name"].lower() == name.lower()), None
    )
    if competitor is None:
        return 0

    existing = {
        f["name"].lower()
        for f in store.list_competitor_features(competitor_id=competitor["id"])
    }
    added = 0
    for feature in get_agent().research_competitor(name):
        if feature["name"].lower() in existing:
            continue
        store.create_competitor_feature(
            competitor_id=competitor["id"],
            name=feature["name"],
            description=feature["description"] or None,
            category=feature["category"] or None,
            source_url=RECALLED,
        )
        added += 1
    return added


def file_product_features(profile: dict) -> int:
    """File the features a chat described for the user's own product."""
    store = current_db()
    existing = {f["title"].lower() for f in store.list_features()}
    added = 0
    for feature in profile.get("features", []):
        if feature["title"].lower() in existing:
            continue
        store.create_feature(
            title=feature["title"],
            description=feature.get("description") or None,
            priority="Medium",
            impact="Medium",
            effort="Medium",
            status="Backlog",
        )
        added += 1
    return added


def render_save_actions(item: dict, index: int) -> None:
    """Offer what a message mentioned, as one-press saves.

    This is the only route into product memory: the agent answers, and filing
    anything is the user's decision, taken here.
    """
    saved = item.get("saved", [])
    already = {entry["label"] for entry in saved}
    offers = [s for s in item.get("suggestions", []) if s["label"] not in already]
    base = f"{st.session_state.current_chat_id}_{index}"

    if offers:
        # Leave the last column empty so two chips do not stretch the full width.
        widths = [1] * len(offers) + [max(1, 4 - len(offers))]
        for column, suggestion in zip(st.columns(widths), offers):
            column.button(
                chip_label(suggestion),
                key=f"save_{base}_{suggestion['label']}",
                use_container_width=True,
                help=f"Files this under {suggestion['kind'].title()}s. You can undo it.",
                on_click=save_suggestion,
                args=(item, suggestion),
            )

    for entry in saved:
        note, undo, _ = st.columns([3, 1, 3])
        note.caption(f"✓ Saved {_shorten(entry['what'], 34)} → {entry['where']}")
        undo.button(
            "Undo",
            key=f"undo_{base}_{entry['label']}",
            use_container_width=True,
            on_click=undo_save,
            args=(item, entry),
        )


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


# Mermaid is loaded in the component's own iframe rather than bundled: the app
# is offline-tolerant everywhere else, and a diagram that fails to draw falls
# back to its source, which is still readable.
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"


def render_diagram(code: str, key: str) -> None:
    """Draw a mermaid diagram in an iframe, with its source one click away."""
    lines = max(3, code.count("\n") + 1)
    height = min(620, 120 + 34 * lines)
    # The diagram source comes from the model, so it is escaped into the div
    # rather than concatenated as markup: mermaid reads the node's text, and an
    # answer containing "</div><script>" stays text instead of becoming one.
    st.iframe(
        f"""
        <div class="mermaid" style="background:{theme.TOKENS['surface']};
             color:{theme.TOKENS['text']};font-family:{theme.FONT_BODY};
             border-radius:10px;padding:12px;">{html.escape(code)}</div>
        <script type="module">
          import mermaid from "{MERMAID_CDN}";
          mermaid.initialize({{
            startOnLoad: true,
            theme: "dark",
            themeVariables: {{
              background: "{theme.TOKENS['surface']}",
              primaryColor: "{theme.TOKENS['surface_hi']}",
              primaryTextColor: "{theme.TOKENS['text']}",
              primaryBorderColor: "{theme.TOKENS['accent']}",
              lineColor: "{theme.TOKENS['dim']}",
              fontFamily: "{theme.FONT_BODY}"
            }}
          }});
        </script>
        """,
        height=height,
    )
    with st.expander("Diagram source"):
        st.code(code, language="mermaid")


def render_reply(text: str, key: str = "") -> None:
    """Render an answer, drawing whatever the model asked to have drawn.

    Prose stays markdown. A chart, table or diagram block becomes the thing it
    describes — and a block that did not validate becomes visible text rather
    than a hole in the answer, so a bad block costs formatting, never content.
    """
    import pandas as pd

    for position, (kind, payload) in enumerate(visuals.parse(text)):
        slot_key = f"{key}_{position}"

        if kind == "text":
            st.markdown(payload)

        elif kind == "chart":
            if payload["title"]:
                st.markdown(f"**{payload['title']}**")
            look = accessibility.appearance(current_settings())
            st.altair_chart(visuals.to_altair(payload, look), width="stretch")
            if payload["note"]:
                st.caption(payload["note"])
            # Identity is never colour-alone, and a chart is never the only way
            # to read the numbers.
            with st.expander("Table view", expanded=look["label_always"]):
                frame = pd.DataFrame(payload["rows"])
                st.dataframe(frame, width="stretch", hide_index=True)

        elif kind == "table":
            if payload["title"]:
                st.markdown(f"**{payload['title']}**")
            st.dataframe(
                pd.DataFrame(payload["rows"], columns=payload["columns"]),
                width="stretch",
                hide_index=True,
            )

        elif kind == "diagram":
            render_diagram(payload, slot_key)

        elif kind == "code":
            st.caption(f"Proxima meant to draw this, but {payload['reason']}.")
            st.code(payload["body"])


def tuned_system_prompt() -> str:
    """SYSTEM_PROMPT plus whatever the settings panel and the project add.

    The assembly lives in memory.py; this only reads session state and hands it
    over. Keeping the two apart is what makes the recall rules testable without
    standing a Streamlit session up.
    """
    return memory.compose_system_prompt(
        SYSTEM_PROMPT,
        language=st.session_state.get("setting_language", "English"),
        scope=st.session_state.get("setting_memory_scope", workspace.DEFAULT_SCOPE),
        style=accessibility.reply_note(current_settings()),
        project=current_project(),
        chats=st.session_state.get("chats", {}),
        current_chat_id=st.session_state.get("current_chat_id"),
        projects=st.session_state.get("projects", {}),
    )


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
    # Chats live on disk, because the workspace each one owns does. So do the
    # projects grouping them, and the recall scope, which is a memory rule
    # rather than a per-visit preference and would be infuriating to reset.
    state = workspace.load_state(USER["id"])
    st.session_state.chats = state["chats"]
    st.session_state.chat_counter = state["counter"]
    st.session_state.projects = state["projects"]
    st.session_state.project_counter = state["project_counter"]
    # Written before the widget exists, which is how Streamlit seeds one.
    st.session_state.setting_memory_scope = state["scope"]
    for key, value in state["settings"].items():
        st.session_state.setdefault(f"set_{key}", value)
    st.session_state.setdefault(
        "set_colour_alone_inverted", not state["settings"]["colour_alone"]
    )

    # Everything filed before accounts and workspaces existed goes to the first
    # account to sign in — whoever was using this machine already. Claiming it
    # is one-time: the next account starts empty rather than inheriting it.
    if workspace.LEGACY_ID not in state["chats"] and workspace.claim_legacy(USER["id"]):
        st.session_state.chats[workspace.LEGACY_ID] = {
            "messages": [],
            "created": datetime.now(),
            "title": workspace.LEGACY_TITLE,
            "ordinal": 0,
            "project_id": None,
        }

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = next(iter(st.session_state.chats), None)

# Guarantee exactly one live chat before anything renders: the sidebar lists
# sessions and the Chat tab reads the current one, so neither can be first.
if not st.session_state.chats or st.session_state.current_chat_id is None:
    new_chat()

# The theme is injected before sign-in, when nobody's settings are known yet.
# This is the second pass: same custom properties, overridden for this account.
overrides = accessibility.css(current_settings())
if overrides:
    st.markdown(f"<style>{overrides}</style>", unsafe_allow_html=True)

# Everything below reads the open chat's workspace, never a shared one.
db = current_db()
competitor_analyzer = CompetitorAnalyzer(db)
ip_analyzer = CopyrightAnalyzer(db)

# Sidebar for chat management
with st.sidebar:
    who, out = st.columns([3, 1], gap="small")
    who.caption(f"Signed in as **{USER['name']}**")
    if out.button("Exit", help=f"Sign out of {USER['email']}", use_container_width=True):
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
        with st.expander(
            f"{project['name']}  ·  {len(filed)}",
            expanded=project_id == open_project_id,
        ):
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

            for chat_id in filed:
                render_chat_row(chat_id)

            if st.button(
                "New chat here", key=f"add_{project_id}", use_container_width=True
            ):
                new_chat(project_id)
                st.rerun()

            with st.popover("Delete project", use_container_width=True):
                st.caption(
                    "The chats inside keep their workspaces — everything saved "
                    "in them survives. They come out of the project unless you "
                    "ask for them to go with it."
                )
                also = st.checkbox(
                    f"Delete the {len(filed)} chat(s) too",
                    key=f"purge_{project_id}",
                )
                if st.button(
                    "Delete", key=f"pdel_{project_id}", use_container_width=True
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
    messages_here = (
        st.session_state.chats.get(st.session_state.current_chat_id, {}).get("messages")
        or []
    )
    if report.is_empty(db, messages_here):
        st.caption("Nothing to export yet — save a feature or run a check first.")
    else:
        st.download_button(
            "Download PDF report",
            # Built on click rather than every rerun: a long transcript takes a
            # moment to typeset, and the sidebar redraws on every keystroke.
            data=lambda: report.build(db, here, messages_here),
            file_name=report.filename(here),
            mime="application/pdf",
            use_container_width=True,
            help="Everything in this workspace — features, board, competitors, IP checks and this chat — as one PDF.",
        )

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
    mark=LOGO_MARK,
)

chat_tab, memory_tab, board_tab, compare_tab, ip_tab = st.tabs(
    ["Chat", "Features", "Board", "Competitor Comparison", "Copyright Analyser"]
)


# ---------------------------------------------------------------- Chat tab
with chat_tab:
    current_chat = st.session_state.chats.get(st.session_state.current_chat_id, {})
    messages = current_chat.get("messages", [])

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


# ------------------------------------------------------------- Features tab
with memory_tab:
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


# ---------------------------------------------------------------- Board tab
COLUMNS = ["Backlog", "To do", "In Progress", "Done"]
SPRINT_STATES = ["Planned", "Active", "Finished"]
PRIORITY_TONE = {"High": "danger", "Medium": "warn", "Low": ""}


with board_tab:
    theme.section(
        "Board",
        note=(
            "Work, as opposed to what the product does — that lives in Features. "
            "A ticket can come from a feature you filed, from something you said "
            "in the chat, or from you typing it here."
        ),
        index="01",
    )

    sprints = db.list_sprints()
    sprint_names = {sprint["id"]: sprint["name"] for sprint in sprints}

    # --- sprint bar
    pick, make, _ = st.columns([3, 2, 2])
    view_options = ["Everything", "Backlog only"] + [s["name"] for s in sprints]
    view = pick.selectbox("Showing", view_options, label_visibility="collapsed")

    with make.popover("New sprint", use_container_width=True):
        with st.form("new_sprint", clear_on_submit=True):
            sprint_name = st.text_input("Name", placeholder=f"Sprint {len(sprints) + 1}")
            sprint_goal = st.text_area("Goal", height=70, placeholder="What this sprint is for")
            span = st.columns(2)
            starts = span[0].date_input("Starts", value=None, format="YYYY-MM-DD")
            ends = span[1].date_input("Ends", value=None, format="YYYY-MM-DD")
            if st.form_submit_button("Create sprint", type="primary"):
                name = sprint_name.strip() or f"Sprint {len(sprints) + 1}"
                db.create_sprint(
                    name=name,
                    goal=sprint_goal.strip() or None,
                    starts=str(starts) if starts else None,
                    ends=str(ends) if ends else None,
                )
                st.session_state.save_toast = f"{name} created."
                st.rerun()

    # --- what the board is showing
    if view == "Backlog only":
        tickets = [t for t in db.list_tickets() if t["sprint_id"] is None]
        active_sprint = None
    elif view == "Everything":
        tickets = db.list_tickets()
        active_sprint = None
    else:
        active_sprint = next((s for s in sprints if s["name"] == view), None)
        tickets = db.list_tickets(sprint_id=active_sprint["id"]) if active_sprint else []

    if active_sprint:
        with st.container(border=True):
            head, state_col, kill = st.columns([4, 2, 1])
            head.markdown(
                f"**{active_sprint['name']}** — {active_sprint.get('goal') or '_no goal set_'}"
            )
            dates = " → ".join(
                x for x in [active_sprint.get("starts"), active_sprint.get("ends")] if x
            )
            if dates:
                head.caption(dates)
            new_state = state_col.selectbox(
                "State",
                SPRINT_STATES,
                index=SPRINT_STATES.index(active_sprint.get("state") or "Planned"),
                key=f"sprint_state_{active_sprint['id']}",
                label_visibility="collapsed",
            )
            if new_state != (active_sprint.get("state") or "Planned"):
                db.update_sprint(active_sprint["id"], state=new_state)
                st.rerun()
            if kill.button("Delete", key=f"del_sprint_{active_sprint['id']}", use_container_width=True):
                db.delete_sprint(active_sprint["id"])
                st.session_state.save_toast = "Sprint deleted — its tickets went back to the backlog."
                st.rerun()

            done = [t for t in tickets if t["status"] == "Done"]
            if tickets:
                st.progress(len(done) / len(tickets), text=f"{len(done)} of {len(tickets)} done")

    # --- ways to get work onto the board
    add_col, scan_col, feat_col, _ = st.columns([2, 2, 2, 1])

    with add_col.popover("Add ticket", use_container_width=True):
        with st.form("new_ticket", clear_on_submit=True):
            ticket_title = st.text_input("Title")
            ticket_desc = st.text_area("Description", height=80)
            row = st.columns(3)
            ticket_priority = row[0].selectbox("Priority", LEVELS, index=1)
            ticket_status = row[1].selectbox("Column", COLUMNS)
            ticket_points = row[2].number_input("Estimate", min_value=0, max_value=21, value=0)
            ticket_sprint = st.selectbox(
                "Sprint", ["Backlog"] + [s["name"] for s in sprints]
            )
            if st.form_submit_button("Add", type="primary") and ticket_title.strip():
                target = next((s["id"] for s in sprints if s["name"] == ticket_sprint), None)
                db.create_ticket(
                    title=ticket_title.strip(),
                    description=ticket_desc.strip() or None,
                    status=ticket_status,
                    priority=ticket_priority,
                    estimate=int(ticket_points) or None,
                    sprint_id=target,
                    origin="typed",
                )
                st.session_state.save_toast = "Ticket added."
                st.rerun()

    if scan_col.button(
        "Suggest tickets from this chat",
        use_container_width=True,
        disabled=not messages,
        help="Reads the conversation for work it implies. Nothing is added until you say so.",
    ):
        with st.spinner("Reading the conversation…"):
            st.session_state.ticket_proposal = get_agent().suggest_tickets(messages)
        st.rerun()

    with feat_col.popover("From a feature", use_container_width=True):
        filed = db.list_features()
        if not filed:
            st.caption("Nothing filed in Features yet.")
        else:
            source = st.selectbox("Feature", [f["title"] for f in filed], key="ticket_from_feature")
            picked_feature = next(f for f in filed if f["title"] == source)
            if st.button("Create ticket", type="primary", key="make_ticket_from_feature"):
                db.create_ticket(
                    title=f"Build {picked_feature['title']}",
                    description=picked_feature.get("description") or None,
                    priority=str(picked_feature.get("priority") or "Medium").title(),
                    feature_id=picked_feature["id"],
                    origin="feature",
                )
                st.session_state.save_toast = f"Ticket created from {picked_feature['title']}."
                st.rerun()

    proposed_tickets = st.session_state.get("ticket_proposal")
    if proposed_tickets is not None:
        with st.container(border=True):
            if not proposed_tickets:
                st.caption("Nothing in this chat reads as work to be done yet.")
            else:
                st.markdown("**Work this chat implies.** Uncheck anything you disagree with.")
                keep = []
                for index, ticket in enumerate(proposed_tickets):
                    label = f"**{ticket['title']}** — {ticket['description']}"
                    if st.checkbox(label, value=True, key=f"tick_{index}_{ticket['title'][:20]}"):
                        keep.append(ticket)
                target_sprint = st.selectbox(
                    "Add to", ["Backlog"] + [s["name"] for s in sprints], key="ticket_target"
                )
                go, _ = st.columns([2, 3])
                if go.button(
                    f"Add {len(keep)} ticket{'s' if len(keep) != 1 else ''}",
                    type="primary",
                    use_container_width=True,
                    disabled=not keep,
                ):
                    target = next((s["id"] for s in sprints if s["name"] == target_sprint), None)
                    for ticket in keep:
                        db.create_ticket(
                            title=ticket["title"],
                            description=ticket["description"] or None,
                            priority=ticket["priority"],
                            sprint_id=target,
                            origin="chat",
                        )
                    st.session_state.pop("ticket_proposal", None)
                    st.session_state.save_toast = f"Added {len(keep)} tickets."
                    st.rerun()
            if st.button("Close", key="ticket_close"):
                st.session_state.pop("ticket_proposal", None)
                st.rerun()

    st.divider()

    # --- the board itself
    if not tickets:
        theme.empty_state(
            label="Board empty",
            title="No tickets here yet",
            body=(
                "Add one by hand, pull the work out of your chat, or turn a filed "
                "feature into a ticket. Sprints are optional — the backlog works "
                "on its own."
            ),
        )
    else:
        # The lanes are a component (see kanban.py) because dragging a card
        # from one column to another is not something Streamlit can observe.
        action = kanban(
            columns=COLUMNS,
            tickets=[
                {
                    "id": ticket["id"],
                    "title": ticket["title"],
                    "description": (ticket.get("description") or "")[:160],
                    "status": ticket.get("status") or COLUMNS[0],
                    "priority": ticket.get("priority") or "Medium",
                    "estimate": ticket.get("estimate"),
                    "sprint": sprint_names.get(ticket.get("sprint_id")),
                    "origin": ticket.get("origin"),
                }
                for ticket in tickets
            ],
            show_sprint=view == "Everything",
        )

        if isinstance(action, dict) and action.get("nonce") != st.session_state.get("board_nonce"):
            st.session_state.board_nonce = action["nonce"]
            if action.get("kind") == "move" and action.get("status") in COLUMNS:
                db.update_ticket(int(action["id"]), status=action["status"])
            elif action.get("kind") == "delete":
                db.delete_ticket(int(action["id"]))
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
        st.rerun()

    sweep = st.session_state.get("ip_sweep")
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


# ------------------------------------------- answering the pending message
# Deliberately the last thing the script does. Streamlit paints a page in the
# order the code runs, so anything after a blocking model call is stuck showing
# the previous run's content until that call returns — which is how the Features
# tab came to disagree with the sidebar about how many features exist. With the
# call down here, every tab is already current before the model is asked
# anything, and the answer streams into the slot the transcript held open.
if pending is not None:
    pending_index, pending_item, slot = pending

    written = ""
    painted = 0
    for piece in get_agent().stream_response(
        pending_item["user"], conversation_history=messages[:pending_index]
    ):
        written += piece
        # Repaint every few words, not every token — each update is a message
        # to the browser.
        if len(written) - painted >= 24:
            painted = len(written)
            cursor = "" if current_settings()["motion"] == "reduced" else " ▍"
            slot.markdown(visuals.strip_blocks(written) + cursor)

    pending_item["agent"] = written
    slot.empty()
    with slot.container():
        render_reply(written, key=f"msg{pending_index}")
    remember_sessions()

# With the answer delivered, have the model read the message back for anything
# worth filing that the keyword rules did not catch — a rival named in passing,
# a feature described rather than requested.
unread = next(
    (m for m in messages if m.get("agent") is not None and not m.get("model_read")),
    None,
)
if unread is not None:
    unread["model_read"] = True
    extra = suggestions_from_model(
        unread["user"],
        get_agent(),
        known_competitors={c["name"] for c in db.list_competitors()},
        existing=unread.get("suggestions", []),
    )
    if extra:
        unread["suggestions"] = merge_suggestions(unread.get("suggestions", []), extra)
    remember_sessions()
    if extra:
        st.rerun()

# A competitor was just filed. Look its product up now — after the page is
# painted, so the save itself stayed instant.
queued = st.session_state.get("research_queue")
if queued:
    with st.spinner(f"Reading up on {queued}…"):
        found = run_research(queued)
    # Cleared only once the lookup has actually returned. Popping it up front
    # loses the work if the run is interrupted part-way — which is exactly what
    # a lookup taking ten seconds invites.
    st.session_state.pop("research_queue", None)
    if found:
        st.session_state.save_toast = f"Recalled {found} {queued} features."
        st.rerun()
