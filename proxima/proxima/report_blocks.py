# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""The typed blocks in an answer, drawn for paper.

The model emits charts, tables and diagrams as fenced blocks; ``visuals``
parses them for the app, and this module draws what it parses. Both read the
same spec, so a chart is the same chart on screen and on the page.

``markdown`` is the way in: it splits a reply into blocks and prose, draws the
blocks, and hands the prose to ``_prose`` below.
"""

from __future__ import annotations

import re
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, KeepTogether, Paragraph, Spacer

try:
    from . import visuals
    from .report_style import (
        CONTENT_WIDTH, DIM, INK, RULE, S,
        _code_block, _empty, _escape, _grid, _inline, _number, _split_row, _truncate,
    )
except ImportError:  # pragma: no cover
    import visuals
    from report_style import (
        CONTENT_WIDTH, DIM, INK, RULE, S,
        _code_block, _empty, _escape, _grid, _inline, _number, _split_row, _truncate,
    )


# How a line of prose announces what it is. The inline marks (bold, italic,
# code) live in report_style with _inline, because every part of the report
# uses them; these four are block structure and only _prose reads them.
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def markdown(text: str, style: ParagraphStyle | None = None) -> list[Flowable]:
    """Turn the agent's reply into flowables.

    The typed blocks come first, through ``visuals.parse`` — the same parser the
    app draws from, so a chart is the same chart on screen and on paper, and a
    block the app rejected is shown as text here too rather than silently
    vanishing. Whatever is left is prose, and goes to ``_prose`` below.
    """
    if not text:
        return []

    segments = visuals.parse(text)
    # No typed block in this text: it is all prose, so skip the reassembly.
    if not any(kind != "text" for kind, _ in segments):
        return _prose(text, style)

    out: list[Flowable] = []
    for kind, payload in segments:
        if kind == "text":
            out += _prose(payload, style)
        elif kind == "chart":
            out += chart_flowables(payload)
        elif kind == "table":
            out += table_flowables(payload)
        elif kind == "diagram":
            out += diagram_flowables(payload)
        elif kind == "code":
            # A block the app could not validate. Say why, then show it, which
            # is what the app does — the reader can still see what was meant.
            out += [
                Paragraph(f"Unrendered block \u2014 {_escape(payload['reason'])}", S["meta"]),
                Spacer(1, 2),
                _code_block(payload["body"].split("\n")),
                Spacer(1, 6),
            ]
    return out


def _prose(text: str, style: ParagraphStyle | None = None) -> list[Flowable]:
    """Markdown with no typed blocks in it.

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


# -------------------------------------------------------------------- blocks

# The same categorical order the app draws with, so a chart does not change
# colour between the screen and the page. They are saturated enough to hold up
# on white; the dark-ground neutrals around them are not, and are not reused.
SERIES_COLOURS = [colors.HexColor(hue) for hue in visuals.CATEGORICAL]

CHART_FONT = "Helvetica"
LABEL_CAP = 30  # a category label longer than this is elided, not wrapped


def _series_matrix(spec: dict) -> tuple[list[str], list[str], list[list[float]]]:
    """The spec's rows as (categories, series names, one value list per series).

    A gap — a series with no row for some category — becomes ``None``, which
    reportlab draws as absent rather than as zero. Zero would be a claim the
    data never made.
    """
    categories: list[str] = []
    for row in spec["rows"]:
        if row["label"] not in categories:
            categories.append(row["label"])

    names = spec.get("series") or []
    if not names:
        lookup = {row["label"]: row["value"] for row in spec["rows"]}
        return categories, [], [[lookup.get(c) for c in categories]]

    matrix = []
    for name in names:
        lookup = {r["label"]: r["value"] for r in spec["rows"] if r.get("series") == name}
        matrix.append([lookup.get(c) for c in categories])
    return categories, names, matrix


def _fits(labels: Sequence[str], size: float) -> float:
    widest = max((stringWidth(_truncate(l, LABEL_CAP), CHART_FONT, size) for l in labels), default=0)
    return widest


def _style_axes(chart, unit: str) -> None:
    for axis in (chart.categoryAxis, chart.valueAxis):
        axis.strokeColor = RULE
        axis.labels.fontName = CHART_FONT
        axis.labels.fontSize = 7
        axis.labels.fillColor = DIM
    chart.valueAxis.gridStrokeColor = RULE
    chart.valueAxis.gridStrokeWidth = 0.3
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.valueMin = 0
    # "60%", not "60.0%". reportlab hands the axis floats; a tick that invents
    # a decimal place implies a precision the data does not have.
    chart.valueAxis.labelTextFormat = lambda v: f"{_number(v)}{unit}"


def _paint(chart, count: int) -> None:
    for index in range(count):
        chart.bars[index].fillColor = SERIES_COLOURS[index % len(SERIES_COLOURS)]
        chart.bars[index].strokeColor = None


def _chart_drawing(spec: dict) -> Drawing | None:
    """One chart spec as a drawing, or None if it cannot be drawn safely."""
    categories, names, matrix = _series_matrix(spec)
    if not categories or not matrix:
        return None

    # Past the palette the tail is folded rather than given an invented hue —
    # the app's rule, applied here so both agree on what the sixth series is.
    if names:
        spec = visuals.fold_series(spec, len(SERIES_COLOURS))
        categories, names, matrix = _series_matrix(spec)

    unit = spec.get("unit", "")
    kind = spec["kind"]
    width = CONTENT_WIDTH
    multi = len(matrix) > 1

    # A legend gets a band of its own above the plot. Overlapping the top tick
    # is how a legend stops being a key and starts being noise.
    legend_band = 18 if multi else 0

    if kind == "bar":
        # Horizontal bars stack bottom-up in reportlab, so the first row would
        # land at the bottom. Reversed here to read top-down, as the app does.
        categories = list(reversed(categories))
        matrix = [list(reversed(values)) for values in matrix]

        row_height = 15 if not multi else 9 * len(matrix) + 8
        height = min(max(len(categories) * row_height + 34, 70), 430) + legend_band
        chart = HorizontalBarChart()
        left = min(_fits(categories, 7) + 10, width * 0.42)
        chart.x, chart.y = left, 16
        chart.width = width - left - 22
        chart.height = height - chart.y - 10 - legend_band
        chart.categoryAxis.categoryNames = [_truncate(c, LABEL_CAP) for c in categories]
    elif kind == "column":
        height = 190 + legend_band
        chart = VerticalBarChart()
        chart.x, chart.y = 34, 32
        chart.width = width - 50
        chart.height = height - chart.y - 12 - legend_band
        chart.categoryAxis.categoryNames = [_truncate(c, 18) for c in categories]
        # Angled when the labels would otherwise collide.
        if _fits(categories, 7) > (chart.width / max(len(categories), 1)) * 0.9:
            chart.categoryAxis.labels.angle = 30
            chart.categoryAxis.labels.dy = -6
            chart.categoryAxis.labels.boxAnchor = "e"
    else:  # line, area
        height = 190 + legend_band
        chart = HorizontalLineChart()
        chart.x, chart.y = 34, 32
        chart.width = width - 50
        chart.height = height - chart.y - 12 - legend_band
        chart.categoryAxis.categoryNames = [_truncate(c, 18) for c in categories]

    chart.data = matrix
    _style_axes(chart, unit)

    if isinstance(chart, HorizontalLineChart):
        for index in range(len(matrix)):
            chart.lines[index].strokeColor = SERIES_COLOURS[index % len(SERIES_COLOURS)]
            chart.lines[index].strokeWidth = 1.6
    else:
        chart.groupSpacing = 6
        chart.barSpacing = 0.5 if multi else 0
        _paint(chart, len(matrix))
        # The number on the bar. With one series there is room for it; with
        # several the bars are too thin and the axis carries the reading.
        if not multi:
            chart.barLabels.fontName = CHART_FONT
            chart.barLabels.fontSize = 7
            chart.barLabels.fillColor = INK
            chart.barLabelFormat = lambda v: f"{_number(v)}{unit}" if v is not None else ""
            chart.barLabels.dx = 4 if kind == "bar" else 0
            chart.barLabels.dy = 0 if kind == "bar" else 4
            chart.barLabels.boxAnchor = "w" if kind == "bar" else "s"

    drawing = Drawing(width, height)
    drawing.add(chart)

    if multi:
        legend = Legend()
        legend.x, legend.y = chart.x, height - 4
        legend.alignment = "right"
        legend.fontName = CHART_FONT
        legend.fontSize = 7
        legend.fillColor = DIM
        legend.columnMaximum = 1
        legend.deltax = 58
        legend.dxTextSpace = 4
        legend.boxAnchor = "nw"
        legend.colorNamePairs = [
            (SERIES_COLOURS[i % len(SERIES_COLOURS)], name) for i, name in enumerate(names)
        ]
        drawing.add(legend)

    return drawing


def chart_flowables(spec: dict) -> list[Flowable]:
    """A chart with its title above and its note below."""
    out: list[Flowable] = []
    if spec.get("title"):
        out.append(Paragraph(_inline(spec["title"]), S["heading"]))

    drawing = _chart_drawing(spec)
    if drawing is None:
        return out + [_empty("This chart had no drawable rows.")]
    out += [Spacer(1, 2), drawing]

    if spec.get("note"):
        out += [Spacer(1, 2), Paragraph(_inline(spec["note"]), S["meta"])]

    # A title stranded at the foot of one page with its chart on the next reads
    # as a heading for whatever follows it. They travel together or not at all.
    return [KeepTogether(out), Spacer(1, 8)]


def table_flowables(spec: dict) -> list[Flowable]:
    out: list[Flowable] = []
    if spec.get("title"):
        out.append(Paragraph(_inline(spec["title"]), S["heading"]))
    out += [
        Spacer(1, 2),
        _grid([spec["columns"]] + [[str(cell) for cell in row] for row in spec["rows"]]),
    ]
    # Short tables keep their heading; a long one has to be free to break, and
    # its repeated header row carries the columns onto the next page anyway.
    if len(spec["rows"]) <= 12:
        return [KeepTogether(out), Spacer(1, 8)]
    return out + [Spacer(1, 8)]


def diagram_flowables(code: str) -> list[Flowable]:
    """Mermaid needs a browser to draw. Paper gets the source, labelled.

    Silently dropping it would lose the only record that the answer contained a
    diagram at all, which matters most in the transcript.
    """
    return [
        Paragraph("Diagram (Mermaid source)", S["heading"]),
        Spacer(1, 2),
        _code_block(code.split("\n")),
        Spacer(1, 8),
    ]

