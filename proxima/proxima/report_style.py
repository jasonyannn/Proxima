# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Ink for the workspace report: palette, type, and the small marks.

The report is paper, not the app. The brand hues carry over from
``theme.TOKENS`` so one palette edit reaches both, but the grounds and type
colours are chosen for white stock — #E9ECF1 on #0A0B0E is the screen's answer
and is invisible printed.

Nothing here knows what a report contains. It is the vocabulary the sections
and the blocks are written in.
"""

from __future__ import annotations

import re
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

try:
    from .theme import TOKENS
except ImportError:  # pragma: no cover
    from theme import TOKENS



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


def _hex(colour: colors.Color) -> str:
    """``#rrggbb`` for a ``<font color=...>`` tag.

    ``hexval()`` returns ``0xrrggbb``, which reportlab's paragraph parser reads
    as a decimal integer and rejects. The hash is not optional.
    """
    return "#" + colour.hexval()[2:]


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


# ---------------------------------------------------------------- text marks

_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<![\*\w])\*(?!\s)([^\*\n]+?)(?<!\s)\*(?!\*)")


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
        Paragraph(f'<font color="{_hex(ACCENT)}">{index}</font>  {label.upper()}', S["eyebrow"]),
        Spacer(1, 3),
        Rule(CONTENT_WIDTH),
        Spacer(1, 9),
    ]


def _empty(note: str) -> Flowable:
    return Paragraph(note, S["empty"])


def _chip(text: str, tone: colors.Color) -> Flowable:
    """One status word, boxed in its semantic colour."""
    chip = Table([[Paragraph(f'<font color="{_hex(tone)}" size="7.5"><b>{_escape(text.upper())}</b></font>', S["meta"])]])
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


def _number(value: float | None) -> str:
    """A value as a reader would write it: 60, 60.5, not 60.0."""
    if value is None:
        return ""
    return f"{value:g}"


def _count(n: int, noun: str) -> str:
    """"1 ticket", "3 tickets" — the s is not free."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

