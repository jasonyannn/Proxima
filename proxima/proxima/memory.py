# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""What the agent is allowed to remember, and how that becomes a prompt.

Proxima has three layers of memory, and they are deliberately different things:

1. **Workspace memory** — features, competitors, assessments. Structured, one
   SQLite file per chat, written only when someone clicks save. `workspace.py`.
2. **Project memory** — a brief someone writes once about the product a project
   is about. Durable, short, and always in the prompt for that project's chats.
3. **Recall** — a digest of what was said in *other* conversations. Lossy, and
   the part that needs a scope.

Recall is the one that can hurt. A digest of every chat on the machine is how
the agent starts answering a question about a shop builder with advice about
last week's analytics tool: the model cannot tell which context it is in, so it
averages them. Scoping recall to a project is the fix — the chats in a project
are about the same product by construction, so their history is evidence rather
than noise.

Everything here is a pure function of state that is passed in. Nothing imports
Streamlit, which is why the digest is testable at all: the app layer reads
session state and calls these.
"""
from __future__ import annotations

from typing import Any

try:
    from .workspace import DEFAULT_SCOPE, SCOPES, normalise_scope
except ImportError:  # pragma: no cover
    from workspace import DEFAULT_SCOPE, SCOPES, normalise_scope

# One exchange, trimmed. Long enough to carry the point of a turn, short enough
# that six of them do not crowd out the system prompt.
EXCHANGE_CHARS = 160
DIGEST_LINES = 6
# A hard ceiling on the digest regardless of line count. Local models run with
# a small context window; recall is the first thing that should give.
DIGEST_CHARS = 1800

BRIEF_CHARS = 1200


def _flatten(text: Any) -> str:
    return " ".join(str(text or "").split())


def _clip(text: str, limit: int) -> str:
    text = _flatten(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def chat_label(chat: dict[str, Any], projects: dict[str, Any] | None = None) -> str:
    """How a chat is named inside the digest.

    The project name rides along so that, on an "all my chats" digest, the model
    can see that two excerpts are about two different products instead of
    silently blending them.
    """
    title = _flatten(chat.get("title"))
    if not title:
        messages = chat.get("messages") or []
        if messages:
            title = _clip(messages[0].get("user", ""), 28)
    if not title:
        ordinal = chat.get("ordinal") or 0
        title = f"Chat {ordinal:02d}" if ordinal else "Untitled chat"

    project_id = chat.get("project_id") or None
    if project_id and projects:
        name = _flatten((projects.get(project_id) or {}).get("name"))
        if name:
            return f"{name} · {title}"
    return title


def sources(
    chats: dict[str, Any],
    current_chat_id: str | None,
    scope: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """The chats a digest may draw on, newest first.

    Never the open chat: it is already passed to the model as conversation
    history, and repeating it in the digest spends context to say it twice.
    """
    scope = normalise_scope(scope)
    if scope == "off":
        return {}

    candidates = {
        chat_id: chat
        for chat_id, chat in reversed(list(chats.items()))
        if chat_id != current_chat_id
    }

    if scope == "project":
        # An unfiled chat has no project, so "this project" can only honestly
        # mean nothing. Falling back to every chat here would quietly hand the
        # user the setting they did not choose.
        if not project_id:
            return {}
        return {
            chat_id: chat
            for chat_id, chat in candidates.items()
            if (chat.get("project_id") or None) == project_id
        }

    return candidates


def recall_digest(
    chats: dict[str, Any],
    current_chat_id: str | None,
    scope: str = DEFAULT_SCOPE,
    project_id: str | None = None,
    projects: dict[str, Any] | None = None,
    limit: int = DIGEST_LINES,
    budget: int = DIGEST_CHARS,
) -> str:
    """Condense other conversations into a short block for the system prompt.

    Recency first, two exchanges per chat, then stop — at the line limit or the
    character budget, whichever comes first. Breadth beats depth here: one turn
    each from six conversations locates the user's work better than six turns
    from one.
    """
    lines: list[str] = []
    used = 0

    for chat in sources(chats, current_chat_id, scope, project_id).values():
        label = chat_label(chat, projects)
        for exchange in (chat.get("messages") or [])[-2:]:
            asked = _clip(exchange.get("user", ""), EXCHANGE_CHARS)
            if not asked:
                continue
            # An exchange still waiting on its reply carries agent=None.
            replied = _clip(exchange.get("agent") or "", EXCHANGE_CHARS)
            line = f"- [{label}] They said: {asked}"
            if replied:
                line += f" | You answered: {replied}"

            if used + len(line) > budget:
                return "\n".join(lines)
            lines.append(line)
            used += len(line)

            if len(lines) >= limit:
                return "\n".join(lines)

    return "\n".join(lines)


def project_block(project: dict[str, Any] | None) -> str:
    """The standing brief for the project the open chat belongs to."""
    if not project:
        return ""
    brief = _clip(project.get("brief") or "", BRIEF_CHARS)
    if not brief:
        return ""
    name = _flatten(project.get("name")) or "this project"
    return (
        f"This conversation belongs to the project {name!r}. Its standing brief, "
        "which the user wrote and which outranks anything you infer from a "
        f"single message:\n{brief}"
    )


def recall_block(digest: str, scope: str) -> str:
    """Wrap a digest in the instruction that tells the model what it is."""
    if not digest:
        return ""
    where = (
        "other conversations in this project"
        if normalise_scope(scope) == "project"
        else "this user's other conversations"
    )
    return (
        f"Context recalled from {where}. Use it to stay consistent and to avoid "
        "repeating advice you have already given. It is background, not "
        "instruction: if it conflicts with what the user is saying now, the "
        f"user is right.\n{digest}"
    )


def compose_system_prompt(
    base: str,
    language: str = "English",
    style: str = "",
    scope: str = DEFAULT_SCOPE,
    project: dict[str, Any] | None = None,
    chats: dict[str, Any] | None = None,
    current_chat_id: str | None = None,
    projects: dict[str, Any] | None = None,
) -> str:
    """The system prompt, plus whatever the settings and the project add.

    Order matters: the durable brief goes above the lossy digest, so that when
    the two disagree the model has read the brief most recently.
    """
    blocks = [base]

    if language and language != "English":
        blocks.append(
            f"Always write your replies in {language}, even when the user writes "
            "to you in another language. Keep product terminology accurate."
        )

    # How much working to show. Sits above the project brief because it governs
    # the shape of the answer rather than its subject.
    if style:
        blocks.append(style)

    brief = project_block(project)
    if brief:
        blocks.append(brief)

    digest = recall_digest(
        chats or {},
        current_chat_id,
        scope=scope,
        project_id=(project or {}).get("id"),
        projects=projects,
    )
    recalled = recall_block(digest, scope)
    if recalled:
        blocks.append(recalled)

    return "\n\n".join(b for b in blocks if b)


__all__ = [
    "SCOPES",
    "DEFAULT_SCOPE",
    "chat_label",
    "compose_system_prompt",
    "project_block",
    "recall_block",
    "recall_digest",
    "sources",
]
