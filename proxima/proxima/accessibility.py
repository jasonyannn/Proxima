# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Settings that change what the app actually does.

The rule this module is written to: **a setting that does not change rendering
is worse than no setting at all.** A toggle labelled "colour blind mode" that
only stores a flag tells someone their need has been handled when it has not.
So every option here reaches either the stylesheet, the chart palette, or the
prompt — and the ones that could not be made real were left out and written
down instead (see NOT_SETTINGS at the bottom).

Three groups:

*Seeing* — text scale, contrast, chart colour strategy, and "never colour
alone", which is the one that matters most: the default palette already clears
the colour-vision separation target, so the real win for a colour-blind reader
is a second channel (direct labels, a table, dashed lines), not a different set
of hues.

*Moving* — reduced motion, larger hit targets, a visible keyboard focus ring.

*Hearing* — the honest answer is that this app has no audio-only information at
all: voice input is optional and produces text you can edit. The one real
setting is alerts that do not disappear on their own, which helps anyone who
needs longer than four seconds to read them.
"""
from __future__ import annotations

from typing import Any

try:
    from . import visuals
except ImportError:  # pragma: no cover
    import visuals

# Every option, with the value used when nothing has been chosen. The defaults
# are the current behaviour, so an existing account sees no change.
DEFAULTS: dict[str, Any] = {
    # Seeing
    "text_scale": "normal",
    "contrast": "normal",
    "chart_colour": "default",
    "colour_alone": True,
    "reading_font": False,
    # Moving
    "motion": "full",
    "big_targets": False,
    "focus_ring": False,
    # Hearing / attention
    "persistent_alerts": False,
    # Ordinary
    "reply_length": "balanced",
}

CHOICES: dict[str, tuple[str, ...]] = {
    "text_scale": ("small", "normal", "large", "larger"),
    "contrast": ("normal", "high"),
    "chart_colour": ("default", "separated", "one_hue"),
    "motion": ("full", "reduced"),
    "reply_length": ("brief", "balanced", "detailed"),
}

LABELS: dict[str, dict[str, str]] = {
    "text_scale": {
        "small": "Small", "normal": "Normal", "large": "Large", "larger": "Largest",
    },
    "contrast": {"normal": "Normal", "high": "High contrast"},
    "chart_colour": {
        "default": "Default palette",
        "separated": "Maximum separation",
        "one_hue": "One hue + labels",
    },
    "motion": {"full": "Full", "reduced": "Reduced"},
    "reply_length": {
        "brief": "Brief", "balanced": "Balanced", "detailed": "Detailed",
    },
}

ROOT_FONT_PX = {"small": 14, "normal": 16, "large": 18, "larger": 21}

# Raised text, hairlines and ground. Every pair here was checked against the
# surface it sits on rather than chosen by eye — see test_accessibility.py,
# which fails if any of them drops below the WCAG AA ratio for body text.
HIGH_CONTRAST = {
    "bg": "#000000",
    "bg_alt": "#050609",
    "surface": "#0B0E14",
    "surface_hi": "#141922",
    "line": "#4A5568",
    "line_soft": "#2E3542",
    "text": "#FFFFFF",
    "dim": "#D6DDE8",
    "faint": "#AEB8C7",
    "accent": "#7CA0FF",
    "accent_hi": "#A8C0FF",
}

# Lexend is on Google Fonts, which the theme already loads from, and is
# designed for reading proficiency. Not a medical device — an option.
READING_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2"
    "?family=Lexend:wght@400;500;600;700&display=swap');"
)

# One hue, monotone lightness, from the documented blue ramp. Identity by
# lightness only works under every kind of colour blindness, but only with a
# second channel — selecting it forces labels on.
ONE_HUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab"]

# The first three slots are the ones that clear the separation floors when any
# two marks can sit side by side. Past three, fold the tail into "Other"
# rather than seat a fourth hue that a protan reader cannot split from it.
SEPARATED_CAP = 3


def normalise(raw: Any) -> dict[str, Any]:
    """A complete, valid settings dict from whatever was stored."""
    settings = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return settings

    for key, default in DEFAULTS.items():
        if key not in raw:
            continue
        value = raw[key]
        if key in CHOICES:
            text = str(value or "").strip().lower()
            settings[key] = text if text in CHOICES[key] else default
        else:
            settings[key] = bool(value)
    return settings


def palette(settings: dict[str, Any]) -> list[str]:
    """The chart hues this reader should get."""
    mode = normalise(settings)["chart_colour"]
    if mode == "one_hue":
        return list(ONE_HUE)
    if mode == "separated":
        return visuals.CATEGORICAL[:SEPARATED_CAP]
    return list(visuals.CATEGORICAL)


def series_cap(settings: dict[str, Any]) -> int:
    """How many series may carry a hue before the tail becomes "Other"."""
    mode = normalise(settings)["chart_colour"]
    return SEPARATED_CAP if mode == "separated" else len(visuals.CATEGORICAL)


def label_always(settings: dict[str, Any]) -> bool:
    """Should every mark carry its value, and the table view be open?

    True when the reader asked not to rely on colour, and forced true for the
    one-hue palette, where colour is carrying nothing at all.
    """
    settings = normalise(settings)
    return (not settings["colour_alone"]) or settings["chart_colour"] == "one_hue"


def appearance(settings: dict[str, Any]) -> dict[str, Any]:
    """Everything the chart builder needs, in one dict."""
    return {
        "palette": palette(settings),
        "cap": series_cap(settings),
        "label_always": label_always(settings),
        "dashed": label_always(settings),
    }


def reply_note(settings: dict[str, Any]) -> str:
    """The prompt line for the chosen answer length."""
    length = normalise(settings)["reply_length"]
    if length == "brief":
        return (
            "Keep this answer short: the recommendation and the single reason it "
            "follows. No preamble, no restating the question, at most six lines "
            "unless the user asks for more."
        )
    if length == "detailed":
        return (
            "Give the full working: the reasoning, the trade-offs you weighed, "
            "what you are assuming, and what would change your answer."
        )
    return ""


def css(settings: dict[str, Any]) -> str:
    """The override stylesheet, or "" when nothing is overridden.

    Written as custom-property overrides on :root wherever possible, because
    the theme is already built on those — so a contrast change is a few
    variables rather than a second copy of the stylesheet.
    """
    settings = normalise(settings)
    blocks: list[str] = []
    imports = ""

    root: list[str] = []
    if settings["contrast"] == "high":
        root += [f"  --px-{k.replace('_', '-')}: {v};" for k, v in HIGH_CONTRAST.items()]
    if settings["reading_font"]:
        imports += READING_FONT_IMPORT
        family = "'Lexend', 'Inter', system-ui, sans-serif"
        root.append(f"  --px-font-body: {family};")
        root.append(f"  --px-font-display: {family};")
    if root:
        blocks.append(":root {\n" + "\n".join(root) + "\n}")

    size = ROOT_FONT_PX[settings["text_scale"]]
    if size != ROOT_FONT_PX["normal"]:
        # rem drives most of Streamlit's own spacing and type, so the whole UI
        # scales together rather than leaving text in fixed-height boxes.
        blocks.append(f"html {{ font-size: {size}px; }}")

    if settings["contrast"] == "high":
        blocks.append(
            '[data-testid="stAppViewContainer"], [data-testid="stSidebar"] '
            "{ background: var(--px-bg); }\n"
            ".px-section-rule, hr { border-color: var(--px-line) !important; }"
        )

    if settings["motion"] == "reduced":
        blocks.append(
            "*, *::before, *::after {\n"
            "  animation-duration: 0.001ms !important;\n"
            "  animation-iteration-count: 1 !important;\n"
            "  transition-duration: 0.001ms !important;\n"
            "  scroll-behavior: auto !important;\n"
            "}"
        )

    if settings["big_targets"]:
        # WCAG 2.5.5 asks for 44px; Streamlit's default control is ~38px.
        blocks.append(
            '[data-testid="stAppViewContainer"] button,\n'
            '[data-testid="stSidebar"] button,\n'
            "input, select, textarea {\n"
            "  min-height: 44px !important;\n"
            "}"
        )

    if settings["focus_ring"]:
        blocks.append(
            ":focus-visible {\n"
            "  outline: 3px solid var(--px-volt) !important;\n"
            "  outline-offset: 2px !important;\n"
            "  border-radius: 4px;\n"
            "}"
        )

    if not blocks:
        return ""
    return imports + "\n\n".join(blocks)


# Written down rather than shipped as a checkbox that does nothing.
#
# - **Screen-reader labelling.** Streamlit owns the DOM; the app cannot add ARIA
#   to widgets it does not render. The tractable part was done instead: every
#   chart has a table view, every status colour ships with a word, and the
#   diagram keeps its source.
# - **Full keyboard navigation.** Same reason. The focus ring makes the order
#   Streamlit already provides visible, which is the part the app controls.
# - **Captions.** There is nothing to caption: no audio or video is ever played.
#   Voice input is optional and lands as editable text.
# - **Colour-blind "simulation" of the UI.** A filter over the whole app is a
#   demo, not an accommodation; the chart palette and the second encoding
#   channel are the parts that actually change what a reader can tell apart.
NOT_SETTINGS = (
    "screen-reader labelling",
    "full keyboard navigation",
    "captions",
    "ui colour simulation",
)

__all__ = [
    "CHOICES",
    "DEFAULTS",
    "LABELS",
    "appearance",
    "css",
    "label_always",
    "normalise",
    "palette",
    "reply_note",
    "series_cap",
]
