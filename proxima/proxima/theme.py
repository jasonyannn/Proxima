# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Visual system for the Proxima UI.

Streamlit gives us the widgets; this module gives them a face. Everything here
is presentation only — no app logic — so the tabs in app.py stay readable.

The look is a dark "instrument panel": a near-black spec-sheet ground with
hairline rules and uppercase monospace labels, warmed up by one confident blue
accent and softly rounded surfaces so it reads friendly rather than clinical.

Two rules worth keeping if you extend this:

1. Style via the tokens below, not with hard-coded hex values, so a palette
   change stays a one-line edit.
2. Target Streamlit through ``data-testid`` attributes. The generated class
   names (``st-emotion-cache-...``) change between releases; the test ids are
   the closest thing to a public API for styling.
"""

from __future__ import annotations

import base64
import html
import pathlib
from functools import lru_cache

import streamlit as st

# --------------------------------------------------------------- design tokens
# Kept as a plain dict so the palette can be inspected (and swapped) at runtime.
TOKENS = {
    # Ground: three steps of near-black, cool rather than neutral.
    "bg": "#0A0B0E",
    "bg_alt": "#0D0F13",
    "surface": "#121620",
    "surface_hi": "#171C27",
    # Hairlines. `line` is visible, `line_soft` is barely there.
    "line": "#242A36",
    "line_soft": "#1A1F29",
    # Type.
    "text": "#E9ECF1",
    "dim": "#98A1B0",
    "faint": "#626B7B",
    # One accent carries every interactive surface.
    "accent": "#4D7CFE",
    "accent_hi": "#7CA0FF",
    "accent_dim": "rgba(77, 124, 254, 0.14)",
    # Hi-vis signal colour, used sparingly: live status, active markers.
    "volt": "#C8F94C",
    # Semantics.
    "ok": "#2ED3A7",
    "warn": "#FFB020",
    "danger": "#FF5A5F",
}

FONT_DISPLAY = "'Space Grotesk', 'Inter', system-ui, sans-serif"
FONT_BODY = "'Inter', system-ui, -apple-system, sans-serif"
FONT_MONO = "'JetBrains Mono', 'SF Mono', ui-monospace, monospace"


def _vars() -> str:
    """Render TOKENS as CSS custom properties."""
    lines = [f"  --px-{key.replace('_', '-')}: {value};" for key, value in TOKENS.items()]
    lines.append(f"  --px-font-display: {FONT_DISPLAY};")
    lines.append(f"  --px-font-body: {FONT_BODY};")
    lines.append(f"  --px-font-mono: {FONT_MONO};")
    return "\n".join(lines)


# The @import must be the first rule in the stylesheet, so it is concatenated in
# front of everything else rather than living inside the main CSS block.
try:
    from .theme_css import _CSS, _FONTS
except ImportError:  # pragma: no cover
    from theme_css import _CSS, _FONTS



def inject() -> None:
    """Load fonts and the stylesheet. Call once, right after set_page_config."""
    st.markdown(
        f"<style>{_FONTS}{_CSS.replace('__VARS__', _vars())}</style>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ helpers
# Every caller-supplied string is escaped: these all render as raw HTML, and
# feature names and competitor names come from user input.


@lru_cache(maxsize=4)
def _data_uri(path: str) -> str:
    """Inline an image. Streamlit serves no static files for raw HTML to link."""
    try:
        return "data:image/png;base64," + base64.b64encode(
            pathlib.Path(path).read_bytes()
        ).decode()
    except OSError:
        return ""


def hero(
    title: str, subtitle: str, eyebrow: str, stats, online: bool, mark: str = ""
) -> None:
    """The masthead: eyebrow, wordmark, blurb, live status and counters.

    ``stats`` is a sequence of (value, label) pairs. ``mark`` is a path to the
    logo glyph, drawn beside the eyebrow.
    """
    state = "live" if online else "down"
    status_text = "Agent online" if online else "LLM offline · fallback"

    # The eyebrow reads "PROXIMA // SUBTITLE"; the separator gets the accent.
    parts = [html.escape(piece.strip()) for piece in eyebrow.split("//")]
    eyebrow_html = "<span class='px-sep'>//</span>".join(parts)

    uri = _data_uri(mark) if mark else ""
    if uri:
        eyebrow_html = f"<img class='px-mark' src='{uri}' alt=''>" + eyebrow_html

    chips = "".join(
        f"<div class='px-chip'><b>{html.escape(str(value))}</b>"
        f"<span>{html.escape(label)}</span></div>"
        for value, label in stats
    )

    st.markdown(
        f"""
        <div class="px-hero">
          <div class="px-hero-top">
            <div class="px-eyebrow">{eyebrow_html}</div>
            <div class="px-status px-status--{state}">
              <span class="px-dot"></span>{html.escape(status_text)}
            </div>
          </div>
          <h1 class="px-title">{html.escape(title)}</h1>
          <p class="px-sub">{html.escape(subtitle)}</p>
          <div class="px-readout">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(label: str, note: str = "", index: str = "") -> None:
    """An uppercase section header with a trailing hairline rule."""
    marker = f"<i>{html.escape(index)}</i>" if index else ""
    st.markdown(
        f"""
        <div class="px-section">
          <div class="px-section-label">{marker}{html.escape(label)}</div>
          <div class="px-section-rule"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if note:
        st.markdown(
            f"<div class='px-section-note'>{html.escape(note)}</div>",
            unsafe_allow_html=True,
        )


def pill(text: str, tone: str = "") -> str:
    """Return a status pill as an HTML string, for inline composition."""
    variant = f" px-pill--{tone}" if tone else ""
    return f"<span class='px-pill{variant}'>{html.escape(text)}</span>"


def pills(items) -> None:
    """Render a row of pills. ``items`` is a sequence of (text, tone) pairs."""
    st.markdown(
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin:2px 0 14px;'>"
        + "".join(pill(text, tone) for text, tone in items)
        + "</div>",
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str, label: str = "No data yet", example: str = "") -> None:
    """A placeholder panel for a view that has nothing to show yet."""
    hint = f"<br><code>{html.escape(example)}</code>" if example else ""
    st.markdown(
        f"""
        <div class="px-empty">
          <div class="px-empty-label">{html.escape(label)}</div>
          <div class="px-empty-title">{html.escape(title)}</div>
          <div class="px-empty-body">{html.escape(body)}{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def demo_banner(names) -> None:
    """Flag that the numbers on screen come from the fictional sample set."""
    listed = ", ".join(html.escape(name) for name in names)
    st.markdown(
        f"""
        <div class="px-demo">
          <span class="px-demo-tag">Demo data</span>
          <div class="px-demo-text">
            <b>{listed}</b> are invented placeholders, not real companies, and
            their feature lists are made up. Every number below is calculated
            from them — replace them with your own research before acting on
            any of it. Clear them from the sidebar.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Risk bands, warmest to hottest. Kept here rather than in the analyser: these
# are presentation choices about how alarming a number should look.
RISK_BANDS = [
    (75, "var(--px-danger)", "rgba(255, 90, 95, 0.16)"),
    (50, "#FF8A3D", "rgba(255, 138, 61, 0.14)"),
    (25, "var(--px-warn)", "rgba(255, 176, 32, 0.12)"),
    (0, "var(--px-faint)", "transparent"),
]


def _risk_paint(score: float) -> tuple[str, str]:
    for floor, colour, fill in RISK_BANDS:
        if score >= floor:
            return colour, fill
    return "var(--px-faint)", "transparent"


def risk_matrix(rows, competitors) -> None:
    """Every feature against every competitor, as one colour-graded grid.

    A table rather than a chart because the useful reading is per cell — which
    feature, against which rival — and because the eye should be able to find
    the hot corner without decoding a legend.
    """
    header = "".join(
        f"<th class='px-rm-rot'><span>{html.escape(name)}</span></th>" for name in competitors
    )

    body = []
    for row in rows:
        worst_colour, _ = _risk_paint(row.worst_score)
        cells = []
        for name in competitors:
            cell = row.per_competitor.get(name)
            score = cell.risk_score if cell else 0.0
            colour, fill = _risk_paint(score)
            title = (
                f"{row.feature_title} vs {name}: {cell.relationship}"
                if cell
                else "no data"
            )
            closest = (
                f"<em>{html.escape(cell.closest_feature)}</em>"
                if cell and cell.closest_feature
                else "<em>—</em>"
            )
            cells.append(
                f"<td style='background:{fill};color:{colour}' title='{html.escape(title)}'>"
                f"<b>{int(round(score))}%</b>{closest}</td>"
            )

        body.append(
            "<tr>"
            f"<th scope='row'>{html.escape(row.feature_title)}</th>"
            f"<td class='px-rm-worst' style='color:{worst_colour}'>"
            f"<b>{int(round(row.worst_score))}%</b>"
            f"<em>{html.escape(row.worst_level)}</em></td>"
            + "".join(cells)
            + "</tr>"
        )

    st.markdown(
        f"""
        <style>
        .px-rm-wrap {{ overflow-x: auto; border: 1px solid var(--px-line);
          border-radius: 12px; background: var(--px-bg-alt); }}
        .px-rm {{ border-collapse: collapse; width: 100%; font-family: var(--px-font-body); }}
        .px-rm th, .px-rm td {{ padding: 10px 12px; text-align: center;
          border-bottom: 1px solid var(--px-line-soft); font-size: 0.82rem; }}
        .px-rm thead th {{ position: sticky; top: 0; background: var(--px-surface);
          font-family: var(--px-font-mono); font-size: 0.62rem; letter-spacing: 0.14em;
          text-transform: uppercase; color: var(--px-dim); font-weight: 600; }}
        .px-rm tbody th {{ text-align: left; color: var(--px-text); font-weight: 600;
          white-space: nowrap; position: sticky; left: 0; background: var(--px-bg-alt); }}
        .px-rm td b {{ display: block; font-size: 0.95rem; font-weight: 600; }}
        .px-rm td em {{ display: block; font-style: normal; font-size: 0.66rem;
          color: var(--px-faint); margin-top: 2px; max-width: 140px; overflow: hidden;
          text-overflow: ellipsis; white-space: nowrap; }}
        .px-rm-worst {{ border-right: 1px solid var(--px-line); }}
        .px-rm tbody tr:hover td {{ filter: brightness(1.25); }}
        </style>
        <div class="px-rm-wrap">
          <table class="px-rm">
            <thead><tr>
              <th style="text-align:left">Your feature</th>
              <th class="px-rm-worst">Worst</th>
              {header}
            </tr></thead>
            <tbody>{''.join(body)}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )
