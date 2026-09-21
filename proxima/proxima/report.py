# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Compile a whole workspace into one PDF.

Everything the tabs show separately — features, board, competitors, IP risk,
and the conversation that produced them — collected into a document you can
send to someone who will never open Proxima.

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

import io
import pathlib
import re
from datetime import datetime
from typing import Any, Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
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
    from .theme import TOKENS
except ImportError:  # pragma: no cover
    from theme import TOKENS


# ------------------------------------------------------------------ palette

# The brand hues come from the UI so one palette edit reaches both. The
# neutrals do not: #E9ECF1 type on #0A0B0E ground is the screen's answer, and
# on paper it is invisible.
ACCENT = colors.HexColor(TOKENS["accent"])
OK = colors.HexColor(TOKENS["ok"])
WARN = colors.HexColor(TOKENS["warn"])
DANGER = colors.HexColor(TOKENS["danger"])

INK = colors.HexColor("#14181F")
DIM = colors.HexColor("#5C6575")
FAINT = colors.HexColor("#8A93A2")
RULE = colors.HexColor("#DCE1E9")
BAND = colors.HexColor("#F4F6FA")
PAPER = colors.white

PAGE = A4
MARGIN = 18 * mm
CONTENT_WIDTH = PAGE[0] - 2 * MARGIN

# Risk and status words map onto the three semantic hues. Anything unrecognised
# stays neutral rather than being forced into a colour it has not earned.
TONES = {
    "high": DANGER,
    "critical": DANGER,
    "urgent": DANGER,
    "open": DANGER,
    "medium": WARN,
    "moderate": WARN,
    "in progress": WARN,
    "low": OK,
    "done": OK,
    "closed": OK,
    "shipped": OK,
}


def _tone(value: str) -> colors.Color:
    return TONES.get(str(value or "").strip().lower(), FAINT)


# ------------------------------------------------------------------- styles


def _styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=INK,
        spaceAfter=5,
    )
    return {
        "body": body,
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=30,
            leading=34,
            spaceAfter=8,
        ),
        "cover_brief": ParagraphStyle(
            "cover_brief",
            parent=body,
            fontSize=11,
            leading=17,
            textColor=DIM,
            spaceAfter=0,
        ),
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=FAINT,
            spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "section",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            spaceBefore=0,
            spaceAfter=2,
        ),
        "item": ParagraphStyle(
            "item",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            spaceAfter=2,
        ),
        "heading": ParagraphStyle(
            "heading",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "meta": ParagraphStyle(
            "meta", parent=body, fontSize=8, leading=11, textColor=FAINT, spaceAfter=0
        ),
        "empty": ParagraphStyle(
            "empty", parent=body, fontName="Helvetica-Oblique", textColor=FAINT
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=body, leftIndent=10, bulletIndent=1, spaceAfter=2
        ),
        "mono": ParagraphStyle(
            "mono",
            parent=body,
            fontName="Courier",
            fontSize=8,
            leading=11,
            textColor=DIM,
            leftIndent=8,
        ),
        "cell": ParagraphStyle("cell", parent=body, fontSize=8.5, leading=12, spaceAfter=0),
        "cell_head": ParagraphStyle(
            "cell_head",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=11,
            textColor=FAINT,
            spaceAfter=0,
        ),
        "speaker": ParagraphStyle(
            "speaker",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=11,
            textColor=ACCENT,
            spaceAfter=2,
        ),
    }


S = _styles()


# ------------------------------------------------------------------ markdown

_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<![\*\w])\*(?!\s)([^\*\n]+?)(?<!\s)\*(?!\*)")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _escape(text: str) -> str:
    """Escape for reportlab's mini-HTML, which a stray ``<`` or ``&`` breaks."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    """Markdown emphasis to reportlab markup, on already-escaped text.

    Code spans go first and are handed straight to a font tag, so a ``*`` that
    happens to live inside backticks is never read as emphasis.
    """
    out = _escape(text)
    out = _CODE_SPAN.sub(r'<font face="Courier" size="8.5">\1</font>', out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    return out


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown(text: str, style: ParagraphStyle | None = None) -> list[Flowable]:
    """Turn the agent's markdown into flowables.

    Not a full parser, and deliberately so: it covers what the model actually
    writes — headings, bullets, numbered lists, fenced code, pipe tables and
    inline emphasis — and anything else falls through as a plain paragraph
    rather than being dropped.
    """
    style = style or S["body"]
    flowables: list[Flowable] = []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.strip().startswith("```"):
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            if block:
                flowables.append(_code_block(block))
            continue

        # A pipe table needs its second line to be the divider; without it this
        # is prose that happens to contain a bar.
        if (
            "|" in line
            and index + 1 < len(lines)
            and _TABLE_DIVIDER.match(lines[index + 1])
            and "|" in lines[index + 1]
        ):
            header = _split_row(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_row(lines[index]))
                index += 1
            flowables.append(_grid([header] + rows))
            continue

        if not line.strip():
            index += 1
            continue

        match = _HEADING.match(line)
        if match:
            flowables.append(Paragraph(_inline(match.group(2)), S["heading"]))
            index += 1
            continue

        match = _BULLET.match(line)
        if match:
            flowables.append(
                Paragraph(_inline(match.group(1)), S["bullet"], bulletText="•")
            )
            index += 1
            continue

        match = _NUMBERED.match(line)
        if match:
            flowables.append(
                Paragraph(
                    _inline(match.group(2)), S["bullet"], bulletText=f"{match.group(1)}."
                )
            )
            index += 1
            continue

        flowables.append(Paragraph(_inline(line), style))
        index += 1

    return flowables


def _code_block(lines: Sequence[str]) -> Flowable:
    body = "<br/>".join(_escape(line) or "&nbsp;" for line in lines)
    table = Table(
        [[Paragraph(body, S["mono"])]], colWidths=[CONTENT_WIDTH], hAlign="LEFT"
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BAND),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _grid(rows: Sequence[Sequence[str]], widths: Sequence[float] | None = None) -> Flowable:
    """A header row plus body rows, ruled the way the UI rules its tables."""
    if not rows:
        return Spacer(1, 0)

    columns = max(len(row) for row in rows)
    widths = widths or [CONTENT_WIDTH / columns] * columns

    data = []
    for position, row in enumerate(rows):
        padded = list(row) + [""] * (columns - len(row))
        style = S["cell_head"] if position == 0 else S["cell"]
        data.append(
            [
                Paragraph(
                    _inline(str(cell)).upper() if position == 0 else _inline(str(cell)),
                    style,
                )
                for cell in padded
            ]
        )

    table = Table(data, colWidths=list(widths), hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


# ------------------------------------------------------------------- pieces


class Rule(Flowable):
    """A hairline, the paper equivalent of the UI's section rules."""

    def __init__(self, width: float, colour: colors.Color = RULE, thickness: float = 0.6):
        super().__init__()
        self.width = width
        self.height = thickness
        self.colour = colour
        self.thickness = thickness

    def draw(self) -> None:
        self.canv.setStrokeColor(self.colour)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 0, self.width, 0)


def _section(index: str, label: str) -> list[Flowable]:
    """The numbered section head the tabs use, set for paper."""
    return [
        CondPageBreak(60),
        Paragraph(f'<font color="{ACCENT.hexval()[2:]}">{index}</font>  {label.upper()}', S["eyebrow"]),
        Spacer(1, 3),
        Rule(CONTENT_WIDTH),
        Spacer(1, 9),
    ]


def _empty(note: str) -> Flowable:
    return Paragraph(note, S["empty"])


def _chip(text: str, tone: colors.Color) -> Flowable:
    """One status word, boxed in its semantic colour."""
    chip = Table([[Paragraph(f'<font color="{tone.hexval()[2:]}" size="7.5"><b>{_escape(text.upper())}</b></font>', S["meta"])]])
    chip.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, tone),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return chip


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ------------------------------------------------------------------ sections


def _cover(project: dict[str, Any], counts: dict[str, int], when: datetime) -> list[Flowable]:
    mark = pathlib.Path(__file__).resolve().parent / "assets" / "proxima-mark.png"
    flowables: list[Flowable] = []

    if mark.exists():
        flowables += [Image(str(mark), width=17 * mm, height=17 * mm), Spacer(1, 14)]

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
            x for x in [str(sprint.get("state") or ""), window, f"{len(group)} tickets"] if x
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
                    Paragraph(f"{len(loose)} tickets in no sprint", S["meta"]),
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

        out.append(KeepTogether(block) if len(theirs) <= 6 else block)
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
        out.append(KeepTogether(block) if len(block) <= 4 else block)
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
    story += _cover(db, counts_for(db), when) if False else _cover(project, counts_for(db), when)
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
