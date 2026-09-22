# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Compile a whole workspace into one PDF.

Everything the tabs show separately — features, board, competitors, IP risk,
and the conversation that produced them — collected into a document you can
send to someone who will never open Proxima.

The document itself: what goes in it, in what order, and how it is bound.
The ink it is drawn with lives in report_style.py; the charts and tables that
appear inside an answer live in report_blocks.py.

Two decisions worth keeping if you extend this:

1. **The report is paper, not the app.** The UI is a near-black instrument
   panel; ink on paper is the opposite. The brand hues carry over from
   ``theme.TOKENS`` so a palette change still reaches here, but the grounds and
   type colours are chosen for white stock.
2. **Nothing is invented.** A section with no data says so. A report that
   quietly omits its empty parts reads as complete, and the reader cannot tell
   the difference between "no competitors" and "competitors not exported".
"""

from __future__ import annotations

from __future__ import annotations

import io
import pathlib
import re
from datetime import datetime
from typing import Any, Sequence

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

try:
    from .report_blocks import markdown
    from .report_style import (
        CONTENT_WIDTH, FAINT, INK, MARGIN, PAGE, RULE, S,
        Rule, _chip, _count, _empty, _escape, _grid, _hex, _inline, _section,
        _tone, _truncate,
    )
except ImportError:  # pragma: no cover
    from report_blocks import markdown
    from report_style import (
        CONTENT_WIDTH, FAINT, INK, MARGIN, PAGE, RULE, S,
        Rule, _chip, _count, _empty, _escape, _grid, _hex, _inline, _section,
        _tone, _truncate,
    )


# ------------------------------------------------------------------ sections


def _cover(project: dict[str, Any], counts: dict[str, int], when: datetime) -> list[Flowable]:
    mark = pathlib.Path(__file__).resolve().parent / "assets" / "proxima-mark.png"
    flowables: list[Flowable] = []

    if mark.exists():
        logo = Image(str(mark), width=17 * mm, height=17 * mm)
        logo.hAlign = "LEFT"
        flowables += [logo, Spacer(1, 14)]

    flowables += [
        Paragraph("PROXIMA  //  PRODUCT INTELLIGENCE REPORT", S["eyebrow"]),
        Spacer(1, 10),
        Paragraph(_escape(project.get("name") or "Untitled workspace"), S["cover_title"]),
    ]

    brief = (project.get("brief") or "").strip()
    if brief:
        flowables += [Spacer(1, 2), Paragraph(_inline(brief), S["cover_brief"])]

    flowables += [Spacer(1, 18), Rule(CONTENT_WIDTH), Spacer(1, 14)]

    # The same tallies the sidebar shows, so the cover and the app agree.
    labels = [
        ("Features", counts["features"]),
        ("Board tickets", counts["tickets"]),
        ("Competitors", counts["competitors"]),
        ("Rival features", counts["rival_features"]),
        ("IP checks", counts["ip"]),
    ]
    cells = [
        [Paragraph(f'<font size="17"><b>{value}</b></font>', S["body"]) for _, value in labels],
        [Paragraph(label.upper(), S["cell_head"]) for label, _ in labels],
    ]
    table = Table(cells, colWidths=[CONTENT_WIDTH / len(labels)] * len(labels), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    flowables += [table, Spacer(1, 14), Rule(CONTENT_WIDTH), Spacer(1, 8)]
    flowables.append(
        Paragraph(
            f"Generated {when.strftime('%d %B %Y at %H:%M')} · "
            "Compiled locally by Proxima · Nothing in this report left this machine.",
            S["meta"],
        )
    )
    return flowables


def _features(rows: Sequence[dict[str, Any]]) -> list[Flowable]:
    out = _section("01", "Features")
    if not rows:
        return out + [_empty("No features recorded yet.")]

    for row in rows:
        block: list[Flowable] = [Paragraph(_escape(row.get("title") or "Untitled"), S["item"])]
        description = (row.get("description") or "").strip()
        if description:
            block += markdown(description)
        block.append(Spacer(1, 3))
        block.append(
            _grid(
                [
                    ["Priority", "Impact", "Effort", "Status"],
                    [
                        str(row.get("priority") or "—").title(),
                        str(row.get("impact") or "—").title(),
                        str(row.get("effort") or "—").title(),
                        str(row.get("status") or "—").title(),
                    ],
                ],
                widths=[CONTENT_WIDTH / 4] * 4,
            )
        )
        out.append(KeepTogether(block))
        out.append(Spacer(1, 11))
    return out


def _board(sprints: Sequence[dict[str, Any]], tickets: Sequence[dict[str, Any]]) -> list[Flowable]:
    out = _section("02", "Board")
    if not tickets and not sprints:
        return out + [_empty("No sprints or tickets recorded yet.")]

    by_sprint: dict[Any, list[dict[str, Any]]] = {}
    for ticket in tickets:
        by_sprint.setdefault(ticket.get("sprint_id"), []).append(ticket)

    def ticket_rows(group: Sequence[dict[str, Any]]) -> Flowable:
        return _grid(
            [["Ticket", "Status", "Priority", "Est."]]
            + [
                [
                    _truncate(t.get("title"), 90),
                    str(t.get("status") or "—"),
                    str(t.get("priority") or "—"),
                    str(t.get("estimate") if t.get("estimate") is not None else "—"),
                ]
                for t in group
            ],
            widths=[CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.16, CONTENT_WIDTH * 0.10],
        )

    for sprint in sprints:
        group = by_sprint.pop(sprint.get("id"), [])
        head: list[Flowable] = [Paragraph(_escape(sprint.get("name") or "Sprint"), S["item"])]
        window = " → ".join(x for x in [sprint.get("starts"), sprint.get("ends")] if x)
        detail = " · ".join(
            x
            for x in [str(sprint.get("state") or ""), window, _count(len(group), "ticket")]
            if x
        )
        head.append(Paragraph(_escape(detail), S["meta"]))
        if sprint.get("goal"):
            head += [Spacer(1, 3), Paragraph(_inline(sprint["goal"]), S["body"])]
        head.append(Spacer(1, 5))
        head.append(ticket_rows(group) if group else _empty("No tickets in this sprint."))
        out.append(KeepTogether(head))
        out.append(Spacer(1, 11))

    # Whatever is left belongs to no sprint. It is still work, so it still ships.
    loose = [t for group in by_sprint.values() for t in group]
    if loose:
        out.append(
            KeepTogether(
                [
                    Paragraph("Backlog", S["item"]),
                    Paragraph(f'{_count(len(loose), "ticket")} in no sprint', S["meta"]),
                    Spacer(1, 5),
                    ticket_rows(loose),
                ]
            )
        )
        out.append(Spacer(1, 11))
    return out


def _competitors(
    rivals: Sequence[dict[str, Any]], rival_features: Sequence[dict[str, Any]]
) -> list[Flowable]:
    out = _section("03", "Competitor comparison")
    if not rivals:
        return out + [_empty("No competitors recorded yet.")]

    grouped: dict[Any, list[dict[str, Any]]] = {}
    for feature in rival_features:
        grouped.setdefault(feature.get("competitor_id"), []).append(feature)

    for rival in rivals:
        block: list[Flowable] = [Paragraph(_escape(rival.get("name") or "Unnamed"), S["item"])]
        meta = " · ".join(
            x for x in [rival.get("website") or "", rival.get("pricing") or ""] if x
        )
        if meta:
            block.append(Paragraph(_escape(meta), S["meta"]))
        for field in ("positioning", "notes"):
            if (rival.get(field) or "").strip():
                block += [Spacer(1, 3)] + markdown(rival[field])

        theirs = grouped.get(rival.get("id"), [])
        block.append(Spacer(1, 4))
        if theirs:
            block.append(
                _grid(
                    [["Feature", "Category", "What it does"]]
                    + [
                        [
                            _truncate(f.get("name"), 48),
                            _truncate(f.get("category"), 24),
                            _truncate(f.get("description"), 150),
                        ]
                        for f in theirs
                    ],
                    widths=[CONTENT_WIDTH * 0.26, CONTENT_WIDTH * 0.18, CONTENT_WIDTH * 0.56],
                )
            )
        else:
            block.append(_empty("No features recorded for this competitor."))

        if len(theirs) <= 6:
            out.append(KeepTogether(block))
        else:
            out.extend(block)
        out.append(Spacer(1, 12))
    return out


def _ip(assessments: Sequence[dict[str, Any]]) -> list[Flowable]:
    out = _section("04", "Copyright & IP risk")
    if not assessments:
        return out + [_empty("No copyright checks run yet.")]

    for row in assessments:
        level = str(row.get("risk_level") or "unknown")
        score = row.get("risk_score")
        header = Table(
            [
                [
                    Paragraph(_escape(row.get("feature_title") or "Untitled"), S["item"]),
                    _chip(
                        f"{level}" + (f"  {float(score):.0f}" if score is not None else ""),
                        _tone(level),
                    ),
                ]
            ],
            colWidths=[CONTENT_WIDTH * 0.74, CONTENT_WIDTH * 0.26],
            hAlign="LEFT",
        )
        header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        out.append(header)
        if (row.get("feature_description") or "").strip():
            out += [Spacer(1, 3), Paragraph(_inline(row["feature_description"]), S["body"])]
        if (row.get("report") or "").strip():
            out.append(Spacer(1, 4))
            out += markdown(row["report"])
        out += [Spacer(1, 6), Rule(CONTENT_WIDTH, RULE, 0.3), Spacer(1, 10)]
    return out


def _signals(
    feedback: Sequence[dict[str, Any]], bugs: Sequence[dict[str, Any]]
) -> list[Flowable]:
    out = _section("05", "Feedback & bugs")
    if not feedback and not bugs:
        return out + [_empty("No feedback or bugs recorded yet.")]

    if feedback:
        out += [
            Paragraph("Customer feedback", S["item"]),
            Spacer(1, 4),
            _grid(
                [["Source", "Sentiment", "What they said"]]
                + [
                    [
                        _truncate(f.get("source"), 30) or "—",
                        str(f.get("sentiment") or "—").title(),
                        _truncate(f.get("content"), 220),
                    ]
                    for f in feedback
                ],
                widths=[CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.15, CONTENT_WIDTH * 0.65],
            ),
            Spacer(1, 12),
        ]

    if bugs:
        out += [
            Paragraph("Bugs", S["item"]),
            Spacer(1, 4),
            _grid(
                [["Bug", "Severity", "Status"]]
                + [
                    [
                        _truncate(b.get("title"), 80),
                        str(b.get("severity") or "—").title(),
                        str(b.get("status") or "—").title(),
                    ]
                    for b in bugs
                ],
                widths=[CONTENT_WIDTH * 0.62, CONTENT_WIDTH * 0.19, CONTENT_WIDTH * 0.19],
            ),
            Spacer(1, 12),
        ]
    return out


def _transcript(messages: Sequence[dict[str, Any]]) -> list[Flowable]:
    out = _section("06", "Conversation")
    exchanges = [m for m in messages if (m.get("user") or m.get("agent"))]
    if not exchanges:
        return out + [_empty("No conversation in this chat yet.")]

    out.append(
        Paragraph(
            "The reasoning behind everything above, in the order it happened.",
            S["meta"],
        )
    )
    out.append(Spacer(1, 10))

    for exchange in exchanges:
        block: list[Flowable] = []
        if (exchange.get("user") or "").strip():
            block += [
                Paragraph("YOU", S["speaker"]),
                Paragraph(_inline(exchange["user"]), S["body"]),
                Spacer(1, 5),
            ]
        if (exchange.get("agent") or "").strip():
            block.append(Paragraph("PROXIMA", S["speaker"]))
            block += markdown(exchange["agent"])
        if len(block) <= 4:
            out.append(KeepTogether(block))
        else:
            out.extend(block)
        out += [Spacer(1, 6), Rule(CONTENT_WIDTH, RULE, 0.3), Spacer(1, 9)]
    return out


# -------------------------------------------------------------------- build


def _furniture(project_name: str, when: datetime):
    """Running footer. The cover carries its own date, so it stays bare."""
    stamp = when.strftime("%d %b %Y")

    def draw(canvas: Canvas, doc: BaseDocTemplate) -> None:
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, MARGIN - 6, PAGE[0] - MARGIN, MARGIN - 6)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(FAINT)
        canvas.drawString(
            MARGIN, MARGIN - 15, f"{_truncate(project_name, 60)} · Proxima · {stamp}"
        )
        canvas.drawRightString(PAGE[0] - MARGIN, MARGIN - 15, str(doc.page))
        canvas.restoreState()

    return draw


def counts_for(db: Any) -> dict[str, int]:
    return {
        "features": len(db.list_features()),
        "tickets": len(db.list_tickets()),
        "competitors": len(db.list_competitors()),
        "rival_features": len(db.list_competitor_features()),
        "ip": len(db.list_ip_assessments()),
    }


def is_empty(db: Any, messages: Sequence[dict[str, Any]] | None = None) -> bool:
    """Nothing to compile? Then the button should say so rather than hand over
    a cover sheet with five zeros on it."""
    if any(counts_for(db).values()):
        return False
    if len(db.list_sprints()) or len(db.list_feedback()) or len(db.list_bugs()):
        return False
    return not [m for m in (messages or []) if (m.get("user") or m.get("agent"))]


def build(
    db: Any,
    project: dict[str, Any] | None = None,
    messages: Sequence[dict[str, Any]] | None = None,
    when: datetime | None = None,
) -> bytes:
    """The whole workspace as one PDF, returned as bytes for a download button.

    ``db`` is any ``DatabaseManager``; ``project`` is the workspace it belongs
    to, or ``None`` for a chat filed under no project.
    """
    when = when or datetime.now()
    project = project or {}
    name = project.get("name") or "Proxima workspace"

    story: list[Flowable] = []
    story += _cover(project, counts_for(db), when)
    story.append(PageBreak())
    story += _features(db.list_features())
    story += _board(db.list_sprints(), db.list_tickets())
    story += _competitors(db.list_competitors(), db.list_competitor_features())
    story += _ip(db.list_ip_assessments())
    story += _signals(db.list_feedback(), db.list_bugs())
    story += _transcript(messages or [])

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 6,
        title=f"{name} — Proxima report",
        author="Proxima",
        subject="Product intelligence report",
    )
    doc.addPageTemplates(
        [
            PageTemplate(
                id="page",
                frames=[
                    Frame(
                        MARGIN,
                        MARGIN + 6,
                        CONTENT_WIDTH,
                        PAGE[1] - 2 * MARGIN - 6,
                        id="body",
                        leftPadding=0,
                        rightPadding=0,
                        topPadding=0,
                        bottomPadding=0,
                    )
                ],
                onPage=_furniture(name, when),
            )
        ]
    )
    doc.build(story)
    return buffer.getvalue()


def filename(project: dict[str, Any] | None, when: datetime | None = None) -> str:
    when = when or datetime.now()
    name = (project or {}).get("name") or "proxima-workspace"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "proxima-workspace"
    return f"{slug}-report-{when.strftime('%Y-%m-%d')}.pdf"

