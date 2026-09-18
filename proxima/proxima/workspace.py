# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""One workspace per chat: each session owns its own product memory.

A chat is a product you are thinking about. Features, competitors and risk
assessments belong to that product, not to the machine — comparing the shop
builder you sketched this morning against competitors saved while discussing
something else produces nonsense, which is what a single shared database gives
you.

So each chat gets its own SQLite file, and the analysers are pointed at the one
belonging to the open chat. Nothing else about them changes: they already took
a database in their constructor.

Chats themselves are stored here too, in a small JSON file. They have to be:
a workspace keyed by a chat id is orphaned the moment the chat it belongs to
disappears, and Streamlit's session state does not survive a restart.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .database import DatabaseManager
    from . import accessibility
except ImportError:  # pragma: no cover
    from database import DatabaseManager
    import accessibility

DATA = Path(__file__).resolve().parent / "data"
USERS = DATA / "users"

# The single database everything shared before workspaces existed. It becomes
# the workspace of one chat rather than being thrown away.
LEGACY_DB = DATA / "product.db"
LEGACY_ID = "chat_legacy"
LEGACY_TITLE = "Earlier work"


def _safe(value: str) -> str:
    """Ids are generated, but they still end up in a path."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))[:80] or "x"


def home(owner: str | int) -> Path:
    """Where one account's chats and workspaces live."""
    return USERS / _safe(owner)


def workspaces_dir(owner: str | int) -> Path:
    return home(owner) / "workspaces"


def sessions_file(owner: str | int) -> Path:
    return home(owner) / "sessions.json"


def db_path(chat_id: str, owner: str | int) -> Path:
    return workspaces_dir(owner) / f"{_safe(chat_id)}.db"


def database_for(chat_id: str, owner: str | int) -> DatabaseManager:
    """The database backing one chat, created on first use."""
    workspaces_dir(owner).mkdir(parents=True, exist_ok=True)
    path = db_path(chat_id, owner)

    store = DatabaseManager(str(path))
    store.init_db()
    return store


def discard(chat_id: str, owner: str | int) -> None:
    """Delete a chat's workspace along with the chat."""
    db_path(chat_id, owner).unlink(missing_ok=True)


def has_legacy_data() -> bool:
    """Is there a pre-workspace database still waiting to be claimed?"""
    if not LEGACY_DB.exists():
        return False
    try:
        store = DatabaseManager(str(LEGACY_DB))
        return bool(store.list_features() or store.list_competitors())
    except Exception:  # pragma: no cover - a corrupt file is simply not offered
        return False


def claim_legacy(owner: str | int) -> bool:
    """Hand the pre-accounts database to one account, once.

    It belongs to whoever was using this machine before accounts existed, which
    can only be the first person to sign in. Claiming renames the source, so
    the next account to be created starts empty instead of inheriting a
    stranger's backlog.
    """
    if not has_legacy_data():
        return False

    target = db_path(LEGACY_ID, owner)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(LEGACY_DB, target)
        LEGACY_DB.rename(LEGACY_DB.with_name("product.imported.db"))
    except OSError:
        return False
    return True


# ----------------------------------------------------------------- projects

# A project is a folder of chats. It exists for the same reason workspaces do:
# a person thinking about one product holds that thought across a dozen
# conversations, and the agent should be able to remember *that* product's
# history without dragging in every unrelated chat on the machine.
#
# Two things hang off a project:
#   - a brief, written once, always in the prompt for its chats;
#   - a recall scope, which decides how far back the agent is allowed to look.
SCOPES = ("off", "project", "all")
DEFAULT_SCOPE = "project"

SCOPE_LABELS = {
    "off": "This chat only",
    "project": "This project",
    "all": "All my chats",
}


def normalise_scope(value: Any) -> str:
    """Accept whatever is on disk and return a scope the app knows.

    Before projects existed the setting was a bool ("Learn from my chats"), so
    True and False are read as their nearest equivalents rather than discarded.
    """
    if value is True:
        return "all"
    if value is False:
        return "off"
    text = str(value or "").strip().lower()
    return text if text in SCOPES else DEFAULT_SCOPE


def chats_in_project(chats: dict[str, Any], project_id: str | None) -> dict[str, Any]:
    """The chats filed under one project, in their existing order.

    ``None`` selects the unfiled ones, which is what a chat gets before anyone
    has put it anywhere.
    """
    return {
        chat_id: chat
        for chat_id, chat in chats.items()
        if (chat.get("project_id") or None) == (project_id or None)
    }


# ----------------------------------------------------------------- sessions

def _blank_state() -> dict[str, Any]:
    return {
        "chats": {},
        "counter": 0,
        "projects": {},
        "project_counter": 0,
        "scope": DEFAULT_SCOPE,
        "settings": dict(accessibility.DEFAULTS),
    }


def load_state(owner: str | int) -> dict[str, Any]:
    """Everything one account has on disk: chats, projects, and the scope.

    One reader for one file. The chats and the projects that group them are
    written together, so reading them apart would let the two drift.
    """
    path = sessions_file(owner)
    if not path.exists():
        return _blank_state()

    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _blank_state()

    chats: dict[str, Any] = {}
    highest = 0
    for chat_id, chat in (raw.get("chats") or {}).items():
        if not isinstance(chat, dict):
            continue
        created = chat.get("created")
        try:
            created = datetime.fromisoformat(created) if created else datetime.now()
        except (TypeError, ValueError):
            created = datetime.now()
        ordinal = int(chat.get("ordinal") or 0)
        highest = max(highest, ordinal)
        chats[chat_id] = {
            "messages": chat.get("messages") or [],
            "created": created,
            "title": chat.get("title") or "",
            "ordinal": ordinal,
            # Absent for every chat written before projects existed, which is
            # exactly right: they start unfiled.
            "project_id": chat.get("project_id") or None,
        }

    projects: dict[str, Any] = {}
    project_highest = 0
    known = {c.get("project_id") for c in chats.values()}
    for project_id, project in (raw.get("projects") or {}).items():
        if not isinstance(project, dict):
            continue
        created = project.get("created")
        try:
            created = datetime.fromisoformat(created) if created else datetime.now()
        except (TypeError, ValueError):
            created = datetime.now()
        ordinal = int(project.get("ordinal") or 0)
        project_highest = max(project_highest, ordinal)
        projects[project_id] = {
            "name": project.get("name") or "",
            "brief": project.get("brief") or "",
            "created": created,
            "ordinal": ordinal,
        }

    # A chat pointing at a project that is no longer there would vanish from
    # the sidebar, which lists chats by project. Unfile it instead.
    for chat in chats.values():
        if chat["project_id"] and chat["project_id"] not in projects:
            chat["project_id"] = None

    return {
        "chats": chats,
        "counter": max(highest, int(raw.get("counter") or 0)),
        "projects": projects,
        "project_counter": max(project_highest, int(raw.get("project_counter") or 0)),
        # "recall" was the old boolean toggle; normalise_scope reads both.
        "scope": normalise_scope(
            raw.get("memory_scope", raw.get("recall", DEFAULT_SCOPE))
        ),
        # An accessibility choice is the last thing that should evaporate on a
        # restart, so it is stored beside the chats rather than in the session.
        "settings": accessibility.normalise(raw.get("settings")),
    }


def load_sessions(owner: str | int) -> tuple[dict[str, Any], int]:
    """The chats and the highest ordinal seen.

    Kept alongside load_state because the MCP server wants nothing else, and
    should not have to know that projects exist to find a workspace file.
    """
    state = load_state(owner)
    return state["chats"], state["counter"]


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def save_state(
    chats: dict[str, Any],
    counter: int,
    owner: str | int,
    projects: dict[str, Any] | None = None,
    project_counter: int = 0,
    scope: str = DEFAULT_SCOPE,
    settings: dict[str, Any] | None = None,
) -> None:
    """Write chats, projects and the recall scope back.

    Small and rewritten whole — there are tens, not thousands, and a partial
    write would lose a conversation.
    """
    home(owner).mkdir(parents=True, exist_ok=True)
    payload = {
        "counter": counter,
        "project_counter": project_counter,
        "memory_scope": normalise_scope(scope),
        "settings": accessibility.normalise(settings),
        "projects": {
            project_id: {
                "name": project.get("name") or "",
                "brief": project.get("brief") or "",
                "created": _iso(project.get("created")),
                "ordinal": project.get("ordinal") or 0,
            }
            for project_id, project in (projects or {}).items()
        },
        "chats": {
            chat_id: {
                "messages": chat.get("messages") or [],
                "created": _iso(chat.get("created") or datetime.now()),
                "title": chat.get("title") or "",
                "ordinal": chat.get("ordinal") or 0,
                "project_id": chat.get("project_id") or None,
            }
            for chat_id, chat in chats.items()
        },
    }

    path = sessions_file(owner)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=1, default=str))
        tmp.replace(path)
    except OSError:
        # Losing the transcript on disk is not worth taking the app down for.
        tmp.unlink(missing_ok=True)


def save_sessions(chats: dict[str, Any], counter: int, owner: str | int) -> None:
    """Write the chats without touching the projects already on disk.

    For callers that only know about chats. Reading the projects back first is
    what stops a chat-only save from deleting them.
    """
    existing = load_state(owner)
    save_state(
        chats,
        counter,
        owner,
        projects=existing["projects"],
        project_counter=existing["project_counter"],
        scope=existing["scope"],
        settings=existing["settings"],
    )
