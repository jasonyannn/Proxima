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
    from .copyright_analyzer import (
        CopyrightAnalyzer,
        CopyrightSweep,
        DISCLAIMER,
        sweep_from_json,
        sweep_to_json,
    )
    from .prompt_box import prompt_box
    from .kanban import kanban
    from . import (
        theme, voice, workspace, landing, memory, visuals, accessibility,
        report, accounts, tabs, sidebar,
    )
    from .tabs import board, chat, compare, copyright, features  # noqa: F401
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
    from copyright_analyzer import (
        CopyrightAnalyzer,
        CopyrightSweep,
        DISCLAIMER,
        sweep_from_json,
        sweep_to_json,
    )
    from prompt_box import prompt_box
    from kanban import kanban
    import theme, voice, workspace, landing, memory, visuals, accessibility
    import report, accounts, tabs, sidebar
    from tabs import board, chat, compare, copyright, features  # noqa: F401


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
    # A refresh is a new Streamlit session, so without this the landing page
    # appears every time the page reloads. See accounts.remembered() for what
    # this does and does not protect.
    st.session_state.user = accounts.remembered()

if st.session_state.user is None:
    signed_in = landing.render(LOGO_MARK)
    if signed_in:
        st.session_state.user = signed_in
        accounts.remember(signed_in["id"])
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

# Session state that belongs to one chat rather than to the app. Streamlit has
# a single namespace for the whole session, so anything left here survives a
# move to another chat — and a copyright sweep or a product profile from one
# product then reads as if it were about the next one. Cleared on the way in,
# where every path that changes chats has to pass, rather than at each of them.
PER_CHAT_STATE = ("ip_sweep", "chat_profile")

if st.session_state.get("open_chat_was") != st.session_state.current_chat_id:
    for key in PER_CHAT_STATE:
        st.session_state.pop(key, None)
    st.session_state.open_chat_was = st.session_state.current_chat_id

# The open chat's transcript, read once here rather than wherever it is first
# needed. Every tab, the sidebar and the answering step at the foot of this file
# work on this one list, and they must all hold the same object: the model's
# reply is written into it in place.
current_chat = st.session_state.chats.get(st.session_state.current_chat_id, {})
messages = current_chat.get("messages", [])

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
sidebar.render(
    USER=USER,
    chat_title=chat_title,
    current_project=current_project,
    db=db,
    delete_chat=delete_chat,
    delete_project=delete_project,
    get_database=get_database,
    messages=messages,
    move_chat=move_chat,
    new_chat=new_chat,
    new_project=new_project,
    remember_sessions=remember_sessions,
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
    pending = tabs.chat.render(
        capture_speech=capture_speech,
        current_settings=current_settings,
        handle_prompt_request=handle_prompt_request,
        messages=messages,
        render_reply=render_reply,
        render_save_actions=render_save_actions,
    )


# ------------------------------------------------------------- Features tab
with memory_tab:
    tabs.features.render(
        db=db,
        file_product_features=file_product_features,
        get_agent=get_agent,
        messages=messages,
    )


# ---------------------------------------------------------------- Board tab
PRIORITY_TONE = {"High": "danger", "Medium": "warn", "Low": ""}


with board_tab:
    tabs.board.render(db=db, get_agent=get_agent, messages=messages)


# ------------------------------------------------- Competitor comparison tab
with compare_tab:
    tabs.compare.render(
        competitor_analyzer=competitor_analyzer,
        db=db,
        get_agent=get_agent,
        messages=messages,
        run_research=run_research,
    )


# --------------------------------------------------- Copyright analyser tab
with ip_tab:
    tabs.copyright.render(
        db=db,
        get_agent=get_agent,
        ip_analyzer=ip_analyzer,
        messages=messages,
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
