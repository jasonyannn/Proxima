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
except ImportError:  # pragma: no cover
    from database import DatabaseManager

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


# ----------------------------------------------------------------- sessions

def load_sessions(owner: str | int) -> tuple[dict[str, Any], int]:
    """Restore the saved chats, newest numbering intact.

    Returns the chats and the highest ordinal seen, so new chats keep counting
    up rather than colliding with one that already exists.
    """
    path = sessions_file(owner)
    if not path.exists():
        return {}, 0

    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}, 0

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
        }

    return chats, max(highest, int(raw.get("counter") or 0))


def save_sessions(chats: dict[str, Any], counter: int, owner: str | int) -> None:
    """Write the chats back. Small and rewritten whole — there are tens, not
    thousands, and a partial write would lose a conversation."""
    home(owner).mkdir(parents=True, exist_ok=True)
    payload = {
        "counter": counter,
        "chats": {
            chat_id: {
                "messages": chat.get("messages") or [],
                "created": (chat.get("created") or datetime.now()).isoformat()
                if isinstance(chat.get("created"), datetime)
                else str(chat.get("created") or ""),
                "title": chat.get("title") or "",
                "ordinal": chat.get("ordinal") or 0,
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
