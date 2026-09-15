"""Which account, and which chat's workspace, an MCP call is talking about.

The app answers this with the browser session: you sign in, you click a chat,
and everything below that point knows where to write. An MCP client has neither
— it opens one connection and holds it, so the answer has to come from the
server's configuration and from the arguments of each call.

So: the account is fixed when the server starts (``--owner``, or the only
account there is), and the workspace is a per-call argument that falls back to
a configured default and then to the most recent chat. That keeps the common
case — one person, one laptop, the chat they were just looking at — free of
ceremony, without ever guessing between two accounts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import proxima_modules as pm


class ResolutionError(Exception):
    """The caller has to be told which account or workspace they meant."""


def _accounts() -> list[dict[str, Any]]:
    """Every local account, oldest first."""
    pm.accounts.init_db()
    import sqlite3
    from contextlib import closing

    connection = sqlite3.connect(str(pm.accounts.ACCOUNTS_DB))
    connection.row_factory = sqlite3.Row
    with closing(connection):
        rows = connection.execute(
            "SELECT id, email, name FROM account ORDER BY id"
        ).fetchall()
    return [
        {"id": int(r["id"]), "email": r["email"], "name": r["name"] or r["email"].split("@")[0]}
        for r in rows
    ]


def resolve_owner(requested: str | None) -> int:
    """Pin the server to one account for its lifetime.

    An id or an email both work, because the id is an implementation detail
    nobody memorises and the email is what a person actually knows.
    """
    accounts = _accounts()

    if requested:
        wanted = str(requested).strip()
        if wanted.isdigit():
            for account in accounts:
                if account["id"] == int(wanted):
                    return account["id"]
            # An id with no account is still usable: the app creates the folder
            # on first write, and refusing here would break a fresh install.
            return int(wanted)
        for account in accounts:
            if account["email"].lower() == wanted.lower():
                return account["id"]
        raise ResolutionError(
            f"No local account for {wanted!r}. Known accounts: "
            + (", ".join(a["email"] for a in accounts) or "none yet")
        )

    if not accounts:
        raise ResolutionError(
            "No Proxima accounts exist yet. Sign up in the app (./run.sh) first, "
            "or pass --owner with the account id you want this server to use."
        )
    if len(accounts) > 1:
        raise ResolutionError(
            "This machine has more than one Proxima account, so the server "
            "cannot guess whose backlog to expose. Pass --owner with one of: "
            + ", ".join(a["email"] for a in accounts)
        )
    return accounts[0]["id"]


def _title_of(chat_id: str, chat: dict[str, Any]) -> str:
    title = (chat.get("title") or "").strip()
    if title:
        return title
    ordinal = chat.get("ordinal") or 0
    return f"Chat {ordinal}" if ordinal else chat_id


@dataclass
class Workspace:
    """One chat's product memory, named the way a person would name it."""

    id: str
    title: str
    created: str
    db_path: str
    exists: bool


class Context:
    """Everything the tools need to find the right SQLite file."""

    def __init__(self, owner: int, default_workspace: str | None = None,
                 read_only: bool = False) -> None:
        self.owner = owner
        self.default_workspace = default_workspace or None
        self.read_only = read_only

    # ------------------------------------------------------------ listing

    def workspaces(self) -> list[Workspace]:
        """Saved chats, newest first, plus any workspace file without a chat.

        An orphaned .db is real work — the pre-accounts database is exactly
        that — so it is listed rather than hidden behind a missing chat record.
        """
        chats, _ = pm.workspace.load_sessions(self.owner)

        found: list[Workspace] = []
        for chat_id, chat in chats.items():
            path = pm.workspace.db_path(chat_id, self.owner)
            found.append(
                Workspace(
                    id=chat_id,
                    title=_title_of(chat_id, chat),
                    created=str(chat.get("created") or ""),
                    db_path=str(path),
                    exists=path.exists(),
                )
            )

        known = {w.id for w in found}
        directory = pm.workspace.workspaces_dir(self.owner)
        if directory.exists():
            for path in sorted(directory.glob("*.db")):
                if path.stem in known:
                    continue
                found.append(
                    Workspace(
                        id=path.stem,
                        title=(
                            pm.workspace.LEGACY_TITLE
                            if path.stem == pm.workspace.LEGACY_ID
                            else path.stem
                        ),
                        created="",
                        db_path=str(path),
                        exists=True,
                    )
                )

        found.sort(key=lambda w: w.created, reverse=True)
        return found

    def default_id(self) -> str | None:
        """The workspace a call gets when it names none."""
        if self.default_workspace:
            return self.default_workspace
        found = self.workspaces()
        return found[0].id if found else None

    # ------------------------------------------------------------ opening

    def resolve(self, workspace: str | None) -> str:
        """Turn an argument into a workspace id, by id or by title.

        Matching on title matters more than it looks: the model calling these
        tools has just read a list that shows titles, and asking it to carry an
        opaque ``chat_3_1789342447.37857`` between calls is how you get a
        silently wrong workspace.
        """
        wanted = (workspace or "").strip()
        if not wanted:
            chosen = self.default_id()
            if not chosen:
                raise ResolutionError(
                    "This account has no chats yet, so there is no workspace to "
                    "read. Start a chat in the app, or pass a workspace id."
                )
            return chosen

        found = self.workspaces()
        for candidate in found:
            if candidate.id == wanted:
                return candidate.id
        lowered = wanted.lower()
        titled = [c for c in found if c.title.lower() == lowered]
        if len(titled) == 1:
            return titled[0].id
        if len(titled) > 1:
            raise ResolutionError(
                f"{len(titled)} chats are called {wanted!r}. Use the workspace "
                "id from list_workspaces instead of the title."
            )
        raise ResolutionError(
            f"No workspace {wanted!r}. Known: "
            + (", ".join(f"{c.id} ({c.title})" for c in found) or "none yet")
        )

    def database(self, workspace: str | None) -> tuple[Any, str]:
        """The DatabaseManager for a workspace, and the id it resolved to."""
        chat_id = self.resolve(workspace)
        return pm.workspace.database_for(chat_id, self.owner), chat_id

    def require_writable(self) -> None:
        if self.read_only:
            raise ResolutionError(
                "This Proxima MCP server is running read-only. Restart it "
                "without --read-only to let tools write to a workspace."
            )


def context_from_env(owner: str | None = None, workspace: str | None = None,
                     read_only: bool = False) -> Context:
    """Build the context, letting the environment stand in for missing flags."""
    return Context(
        owner=resolve_owner(owner or os.environ.get("PROXIMA_OWNER")),
        default_workspace=workspace or os.environ.get("PROXIMA_WORKSPACE"),
        read_only=read_only or os.environ.get("PROXIMA_MCP_READ_ONLY", "") .lower()
        in {"1", "true", "yes"},
    )
