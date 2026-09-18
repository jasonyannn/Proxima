# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Turning an answer into things you can look at.

When someone asks for "the breakdown" or "the percentages", prose is the wrong
answer. The model is good at deciding *what* the numbers are and bad at drawing
them, so the split here is: the model emits a small typed block, and this module
draws it. Nothing is parsed out of sentences — if it is not in a block, it is
text.

The contract is three fenced blocks in the reply:

    ```proxima-chart
    {"kind": "bar", "title": "...", "unit": "%", "data": [{"label": "...", "value": 62}]}
    ```
    ```proxima-table
    {"title": "...", "columns": ["A", "B"], "rows": [["x", 1]]}
    ```
    ```mermaid
    flowchart TD
      A --> B
    ```

Two rules the rest of the module exists to enforce:

1. **A malformed block never breaks the answer.** A local model will
   occasionally emit trailing commas, a stray unit like "62%" where a number
   belongs, or a chart with no rows at all. Every one of those degrades to
   showing the block as text, never to a traceback in the middle of a reply.
2. **Colour is assigned by the job, not by the series index.** One series gets
   one hue; several get the fixed categorical order below, never a cycled or
   generated hue.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Drawn from the app's own palette (theme.TOKENS) and validated against the
# chart surface #121620 for lightness band, chroma, CVD separation, normal
# vision separation and contrast. Assigned in this order and never cycled:
# past the end the tail folds into "Other" rather than inventing a hue.
ACCENT = "#4D7CFE"
CATEGORICAL = [ACCENT, "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]

GRID = "#242A36"
TEXT = "#E9ECF1"
DIM = "#98A1B0"
SURFACE = "#121620"

# A bar per row; past this a chart stops being readable and a table is the
# honest form. The model is told the same number.
MAX_ROWS = 24
MAX_COLUMNS = 8
MAX_TABLE_ROWS = 50

KINDS = ("bar", "column", "line", "area")

FENCE = re.compile(
    r"```[ \t]*(proxima-chart|proxima-table|mermaid)[ \t]*\r?\n(.*?)(?:```|\Z)",
    re.DOTALL | re.IGNORECASE,
)

# "62%", "1,200", "$4.50" — a model writing for a human, where a number is
# wanted. Pulled apart rather than rejected.
NUMERIC = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")


class BlockError(Exception):
    """A block that cannot be drawn. Carries what to show instead."""


def _loads(raw: str) -> Any:
    """Parse JSON a small model actually produces.

    Trailing commas and a ``json`` language tag on the inner fence are the two
    things llama-class models get wrong often enough to be worth handling; the
    rest is a genuine error.
    """
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise BlockError(f"could not read the block as JSON ({exc.msg})") from None


def to_number(value: Any) -> float | None:
    """A float from whatever the model put there, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = NUMERIC.search(str(value or ""))
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


def _rows(spec: dict) -> list[dict]:
    """Accept the two shapes a model reaches for.

    Either ``data`` as a list of {label, value} objects, or ``labels`` and
    ``values`` as parallel lists. Both are common; neither is worth a fight.
    """
    data = spec.get("data")
    if isinstance(data, dict):
        data = [{"label": k, "value": v} for k, v in data.items()]

    if not isinstance(data, list):
        labels, values = spec.get("labels"), spec.get("values")
        if isinstance(labels, list) and isinstance(values, list):
            data = [
                {"label": label, "value": value}
                for label, value in zip(labels, values)
            ]
        else:
            raise BlockError("the chart has no data rows")

    rows = []
    for entry in data[:MAX_ROWS]:
        if not isinstance(entry, dict):
            continue
        label = str(
            entry.get("label", entry.get("name", entry.get("category", "")))
        ).strip()
        value = to_number(entry.get("value", entry.get("score", entry.get("y"))))
        if not label or value is None:
            continue
        series = entry.get("series") or entry.get("group")
        row = {"label": label, "value": value}
        if series:
            row["series"] = str(series).strip()
        rows.append(row)

    if not rows:
        raise BlockError("none of the chart's rows had both a label and a number")
    return rows


def chart_spec(raw: str) -> dict:
    """Validate one chart block into something drawable."""
    spec = _loads(raw)
    if not isinstance(spec, dict):
        raise BlockError("the chart block was not a JSON object")

    kind = str(spec.get("kind", spec.get("type", "bar"))).strip().lower()
    if kind in ("barh", "horizontal", "horizontal_bar"):
        kind = "bar"
    if kind not in KINDS:
        kind = "bar"

    rows = _rows(spec)
    series = sorted({r["series"] for r in rows if r.get("series")})

    return {
        "kind": kind,
        "title": str(spec.get("title", "")).strip(),
        "unit": str(spec.get("unit", "")).strip()[:8],
        "note": str(spec.get("note", "")).strip(),
        "rows": rows,
        "series": series,
    }


def table_spec(raw: str) -> dict:
    """Validate one table block."""
    spec = _loads(raw)
    if not isinstance(spec, dict):
        raise BlockError("the table block was not a JSON object")

    columns = spec.get("columns") or spec.get("headers")
    rows = spec.get("rows") or spec.get("data")

    # A list of objects is the other natural shape for a table.
    if columns is None and isinstance(rows, list) and rows and isinstance(rows[0], dict):
        columns = list(rows[0])
        rows = [[row.get(c, "") for c in columns] for row in rows]

    if not isinstance(columns, list) or not columns:
        raise BlockError("the table has no columns")
    if not isinstance(rows, list) or not rows:
        raise BlockError("the table has no rows")

    columns = [str(c).strip() for c in columns[:MAX_COLUMNS]]
    shaped = []
    for row in rows[:MAX_TABLE_ROWS]:
        if isinstance(row, dict):
            row = [row.get(c, "") for c in columns]
        if not isinstance(row, list):
            continue
        # Pad and trim so a ragged row cannot break the frame.
        row = [("" if cell is None else cell) for cell in row[: len(columns)]]
        row += [""] * (len(columns) - len(row))
        shaped.append(row)

    if not shaped:
        raise BlockError("none of the table's rows were usable")

    return {
        "title": str(spec.get("title", "")).strip(),
        "columns": columns,
        "rows": shaped,
    }


def parse(reply: str) -> list[tuple[str, Any]]:
    """Split a reply into things to render, in order.

    Returns ``(kind, payload)`` pairs where kind is text / chart / table /
    diagram, and — for a block that failed validation — ``code``, carrying the
    original text so the answer still shows what the model meant.
    """
    if not reply:
        return []

    segments: list[tuple[str, Any]] = []
    cursor = 0

    for match in FENCE.finditer(reply):
        before = reply[cursor : match.start()]
        if before.strip():
            segments.append(("text", before.strip()))
        cursor = match.end()

        tag = match.group(1).lower()
        body = match.group(2)

        if tag == "mermaid":
            code = body.strip()
            if code:
                segments.append(("diagram", code))
            continue

        try:
            if tag == "proxima-chart":
                segments.append(("chart", chart_spec(body)))
            else:
                segments.append(("table", table_spec(body)))
        except BlockError as exc:
            segments.append(("code", {"reason": str(exc), "body": body.strip()}))

    rest = reply[cursor:]
    if rest.strip():
        segments.append(("text", rest.strip()))

    return segments


def has_visuals(reply: str) -> bool:
    return any(kind in ("chart", "table", "diagram") for kind, _ in parse(reply))


def strip_blocks(reply: str) -> str:
    """The prose alone, for the moments a half-written block would be noise.

    Used while the answer is still streaming: a partially written JSON body
    scrolling past is worse than nothing, so it is held back until the fence
    closes and the block can be drawn.
    """
    if not reply:
        return ""
    text = FENCE.sub("\n", reply)
    # An unterminated fence — the model is still mid-block.
    text = re.sub(
        r"```[ \t]*(proxima-chart|proxima-table|mermaid)[ \t]*\r?\n.*\Z",
        "\n",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_altair(spec: dict):
    """An Altair chart for a validated spec.

    Imported lazily: parsing is the part that has to work everywhere (the tests
    exercise it without a plotting stack), and altair arrives with Streamlit.
    """
    import altair as alt
    import pandas as pd

    frame = pd.DataFrame(spec["rows"])
    multi = bool(spec["series"])
    unit = spec["unit"]
    axis_title = f"Value ({unit})" if unit else "Value"

    base = alt.Chart(frame)
    encode: dict[str, Any] = {}

    if multi:
        # Identity is the job, so: fixed categorical order, a legend always
        # present, and hue never generated past the palette.
        encode["color"] = alt.Color(
            "series:N",
            scale=alt.Scale(
                domain=spec["series"],
                range=CATEGORICAL[: len(spec["series"])] or [ACCENT],
            ),
            legend=alt.Legend(title=None, labelColor=DIM, symbolType="square"),
        )
    else:
        # One series: one hue. No legend — the title names it.
        encode["color"] = alt.value(ACCENT)

    quantitative = alt.X(
        "value:Q", title=axis_title, axis=alt.Axis(grid=True, gridColor=GRID)
    )
    categorical = alt.Y(
        "label:N", title=None, sort=None, axis=alt.Axis(labelColor=DIM, labelLimit=220)
    )

    if spec["kind"] == "bar":
        # Horizontal: product labels are words, not codes, and they need room.
        mark = base.mark_bar(cornerRadius=4, height={"band": 0.62}).encode(
            x=quantitative, y=categorical, **encode
        )
    elif spec["kind"] == "column":
        mark = base.mark_bar(cornerRadius=4, width={"band": 0.62}).encode(
            x=alt.X("label:N", title=None, sort=None, axis=alt.Axis(labelColor=DIM)),
            y=alt.Y("value:Q", title=axis_title, axis=alt.Axis(grid=True, gridColor=GRID)),
            **encode,
        )
    elif spec["kind"] == "area":
        mark = base.mark_area(opacity=0.85, line=True).encode(
            x=alt.X("label:N", title=None, sort=None, axis=alt.Axis(labelColor=DIM)),
            y=alt.Y("value:Q", title=axis_title, axis=alt.Axis(grid=True, gridColor=GRID)),
            **encode,
        )
    else:
        mark = base.mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=60)).encode(
            x=alt.X("label:N", title=None, sort=None, axis=alt.Axis(labelColor=DIM)),
            y=alt.Y("value:Q", title=axis_title, axis=alt.Axis(grid=True, gridColor=GRID)),
            **encode,
        )

    layers = [mark]

    # Direct labels on bars: with few rows the number belongs on the mark, not
    # only on an axis the eye has to travel back to. Text wears a text colour,
    # never the series colour.
    if spec["kind"] in ("bar", "column") and not multi and len(spec["rows"]) <= 12:
        label = f"format(datum.value, '.4') + '{unit}'" if unit else "format(datum.value, '.4')"
        text_mark = base.mark_text(color=TEXT, fontSize=11, dx=6 if spec["kind"] == "bar" else 0,
                                   dy=0 if spec["kind"] == "bar" else -8,
                                   align="left" if spec["kind"] == "bar" else "center")
        if spec["kind"] == "bar":
            layers.append(text_mark.encode(x="value:Q", y=categorical, text=alt.Text("value:Q", format=".4")))
        else:
            layers.append(
                text_mark.encode(
                    x=alt.X("label:N", sort=None), y="value:Q",
                    text=alt.Text("value:Q", format=".4"),
                )
            )

    chart = alt.layer(*layers) if len(layers) > 1 else mark
    return chart.properties(
        height=max(140, 34 * len(spec["rows"])) if spec["kind"] == "bar" else 260,
        background=SURFACE,
    ).configure_view(stroke=None).configure_axis(
        labelColor=DIM, titleColor=DIM, domainColor=GRID, tickColor=GRID
    )


# --------------------------------------------------------------- asking for it

# A 3B model reads the system prompt and then writes a markdown table anyway:
# the instruction is 3000 characters behind it by the time it answers. What
# actually works is a short, imperative reminder immediately before the answer
# begins, so the request for a block is the most recent thing in context.
#
# These are matched against the user's message, not the model's reply.
CHART_WORDS = re.compile(
    r"\b(percent\w*|%|breakdown|break down|statistic\w*|stats|metrics|score\w*|"
    r"ranking|rank|distribution|split|proportion\w*|share|chart|graph|plot|"
    r"visuali[sz]\w*|compare|comparison|benchmark\w*|how much|how many|numbers)\b",
    re.IGNORECASE,
)
DIAGRAM_WORDS = re.compile(
    r"\b(diagram|flow ?chart|flow|architecture|workflow|work flow|process|pipeline|"
    r"sequence|state machine|user journey|sitemap|wireframe|map out|mind ?map)\b",
    re.IGNORECASE,
)
TABLE_WORDS = re.compile(
    r"\b(table|matrix|side by side|side-by-side|tabulate|grid|checklist)\b",
    re.IGNORECASE,
)


def wants_visual(text: str) -> set[str]:
    """Which kinds of visual the user's message is asking for, if any."""
    text = str(text or "")
    wanted = set()
    if CHART_WORDS.search(text):
        wanted.add("chart")
    if DIAGRAM_WORDS.search(text):
        wanted.add("diagram")
    if TABLE_WORDS.search(text):
        wanted.add("table")
    return wanted


# Schematic on purpose. An example with real labels and real numbers gets copied
# as content by a small model — the first version of this shipped "Logo
# similarity / 72%" and llama3.2 answered with those exact values for an
# unrelated product.
DIRECTIVES = {
    "chart": (
        "The user asked for numbers, so your answer MUST contain a chart block. "
        "Do not put the numbers in a markdown table and do not put them in a "
        "bulleted list — use this block, with your own labels and your own "
        "values:\n"
        '```proxima-chart\n'
        '{"kind": "bar", "title": "<what these numbers measure>", "unit": "%", '
        '"data": [{"label": "<first thing>", "value": 0}, '
        '{"label": "<second thing>", "value": 0}], '
        '"note": "<say here if these are your estimate rather than a measurement>"}\n'
        "```"
    ),
    "table": (
        "The user asked for a table, so your answer MUST contain a table block, "
        "not a markdown table:\n"
        '```proxima-table\n'
        '{"title": "<what this lists>", "columns": ["<column>", "<column>"], '
        '"rows": [["<cell>", "<cell>"]]}\n'
        "```"
    ),
    "diagram": (
        "The user asked about a flow or a structure, so your answer MUST contain "
        "a diagram block:\n"
        "```mermaid\n"
        "flowchart TD\n"
        "  A[<first step>] --> B[<next step>]\n"
        "```"
    ),
}


def directive(wanted: set[str]) -> str:
    """The reminder to append to a turn, or "" when nothing was asked for.

    Only ever one block is demanded. Asking a small model for three at once
    reliably gets one malformed one; chart wins because it is the form the
    other two are usually a worse substitute for.
    """
    for kind in ("chart", "table", "diagram"):
        if kind in wanted:
            return DIRECTIVES[kind]
    return ""


def turn_reminder(user_input: str) -> str:
    """The directive for one user message, ready to append to the prompt."""
    text = directive(wants_visual(user_input))
    return f"\n\n{text}\n" if text else ""


__all__ = [
    "ACCENT",
    "CATEGORICAL",
    "BlockError",
    "chart_spec",
    "directive",
    "has_visuals",
    "parse",
    "strip_blocks",
    "table_spec",
    "to_altair",
    "to_number",
    "turn_reminder",
    "wants_visual",
]
