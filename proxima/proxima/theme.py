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

import html

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
_FONTS = (
    "@import url('https://fonts.googleapis.com/css2"
    "?family=Inter:wght@400;500;600;700"
    "&family=Space+Grotesk:wght@500;600;700"
    "&family=JetBrains+Mono:wght@400;500;600&display=swap');"
)

_CSS = """
/* ============================================================ foundation === */
:root {
__VARS__
}

html, body, [data-testid="stAppViewContainer"] {
  background: var(--px-bg);
  color: var(--px-text);
  font-family: var(--px-font-body);
  font-feature-settings: "cv05" 1, "ss03" 1;
  -webkit-font-smoothing: antialiased;
}

/* A faint engineering grid over the whole app. Low enough contrast that it
   reads as texture, not as a table. */
[data-testid="stAppViewContainer"]::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    linear-gradient(var(--px-line-soft) 1px, transparent 1px),
    linear-gradient(90deg, var(--px-line-soft) 1px, transparent 1px);
  background-size: 64px 64px;
  opacity: 0.42;
  mask-image: radial-gradient(ellipse 120% 80% at 50% 0%, #000 10%, transparent 78%);
}

[data-testid="stHeader"] {
  background: transparent;
  backdrop-filter: blur(8px);
}

[data-testid="stMainBlockContainer"] {
  position: relative;
  z-index: 1;
  padding-top: 2.6rem;
  max-width: 1180px;
}

/* ================================================================ type === */
h1, h2, h3, h4, h5 {
  font-family: var(--px-font-display);
  letter-spacing: -0.02em;
  color: var(--px-text);
}

h1 { font-weight: 700; }
h2, h3 { font-weight: 600; }

/* Streamlit's st.caption — quiet supporting copy. */
[data-testid="stCaptionContainer"], .stCaption {
  color: var(--px-faint) !important;
  font-size: 0.78rem;
  letter-spacing: 0.01em;
}

code, pre, kbd {
  font-family: var(--px-font-mono) !important;
}

/* =============================================================== hero === */
.px-hero {
  position: relative;
  border: 1px solid var(--px-line);
  border-radius: 14px;
  padding: 30px 32px 26px;
  margin-bottom: 30px;
  overflow: hidden;
  background:
    radial-gradient(900px 320px at 82% -30%, rgba(77, 124, 254, 0.16), transparent 62%),
    radial-gradient(600px 260px at 8% 130%, rgba(200, 249, 76, 0.05), transparent 60%),
    linear-gradient(160deg, var(--px-surface) 0%, var(--px-bg-alt) 100%);
}

/* Registration marks in the corners — the archive/spec-sheet cue. */
.px-hero::after {
  content: "";
  position: absolute;
  inset: 11px;
  border-radius: 8px;
  pointer-events: none;
  background:
    linear-gradient(var(--px-line) 0 0) 0 0 / 12px 1px no-repeat,
    linear-gradient(var(--px-line) 0 0) 0 0 / 1px 12px no-repeat,
    linear-gradient(var(--px-line) 0 0) 100% 0 / 12px 1px no-repeat,
    linear-gradient(var(--px-line) 0 0) 100% 0 / 1px 12px no-repeat,
    linear-gradient(var(--px-line) 0 0) 0 100% / 12px 1px no-repeat,
    linear-gradient(var(--px-line) 0 0) 0 100% / 1px 12px no-repeat,
    linear-gradient(var(--px-line) 0 0) 100% 100% / 12px 1px no-repeat,
    linear-gradient(var(--px-line) 0 0) 100% 100% / 1px 12px no-repeat;
}

.px-hero-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.px-eyebrow {
  font-family: var(--px-font-mono);
  font-size: 0.68rem;
  font-weight: 500;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--px-faint);
}

.px-eyebrow .px-sep { color: var(--px-accent); margin: 0 8px; }

.px-title {
  font-family: var(--px-font-display);
  font-size: clamp(2rem, 4.4vw, 3.05rem);
  font-weight: 700;
  line-height: 0.98;
  letter-spacing: -0.035em;
  margin: 0 0 12px;
  background: linear-gradient(96deg, #FFFFFF 12%, #C3D2F5 58%, var(--px-accent-hi) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.px-sub {
  color: var(--px-dim);
  font-size: 0.96rem;
  max-width: 54ch;
  margin: 0 0 22px;
  line-height: 1.55;
}

/* ---- live status chip (top right of the hero) */
.px-status {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 7px 13px;
  border: 1px solid var(--px-line);
  border-radius: 999px;
  background: rgba(10, 11, 14, 0.6);
  font-family: var(--px-font-mono);
  font-size: 0.66rem;
  font-weight: 500;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--px-dim);
  white-space: nowrap;
}

.px-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: var(--px-faint);
}

.px-status--live .px-dot {
  background: var(--px-volt);
  box-shadow: 0 0 0 0 rgba(200, 249, 76, 0.55);
  animation: px-pulse 2.4s ease-out infinite;
}

.px-status--live { color: var(--px-text); border-color: rgba(200, 249, 76, 0.28); }

.px-status--down .px-dot { background: var(--px-warn); }
.px-status--down { border-color: rgba(255, 176, 32, 0.3); }

@keyframes px-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(200, 249, 76, 0.5); }
  70%  { box-shadow: 0 0 0 7px rgba(200, 249, 76, 0); }
  100% { box-shadow: 0 0 0 0 rgba(200, 249, 76, 0); }
}

@media (prefers-reduced-motion: reduce) {
  .px-status--live .px-dot { animation: none; }
}

/* ---- the counter strip along the bottom of the hero */
.px-readout {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.px-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--px-line);
  border-radius: 9px;
  background: rgba(18, 22, 32, 0.72);
}

.px-chip b {
  font-family: var(--px-font-display);
  font-size: 1.02rem;
  font-weight: 600;
  color: var(--px-text);
  letter-spacing: -0.01em;
}

.px-chip span {
  font-family: var(--px-font-mono);
  font-size: 0.62rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--px-faint);
}

/* ====================================================== section headers === */
.px-section {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 6px 0 4px;
}

.px-section-label {
  font-family: var(--px-font-mono);
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--px-dim);
  white-space: nowrap;
}

.px-section-label i {
  font-style: normal;
  color: var(--px-accent);
  margin-right: 9px;
}

.px-section-rule {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--px-line), transparent);
}

.px-section-note {
  color: var(--px-faint);
  font-size: 0.82rem;
  margin: 8px 0 18px;
  line-height: 1.55;
  max-width: 72ch;
}

/* ============================================================== pills === */
.px-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--px-line);
  background: var(--px-surface);
  font-family: var(--px-font-mono);
  font-size: 0.64rem;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--px-dim);
}

.px-pill--ok     { color: var(--px-ok);     border-color: rgba(46, 211, 167, 0.32); background: rgba(46, 211, 167, 0.08); }
.px-pill--warn   { color: var(--px-warn);   border-color: rgba(255, 176, 32, 0.32); background: rgba(255, 176, 32, 0.08); }
.px-pill--danger { color: var(--px-danger); border-color: rgba(255, 90, 95, 0.32);  background: rgba(255, 90, 95, 0.08); }
.px-pill--accent { color: var(--px-accent-hi); border-color: rgba(77, 124, 254, 0.34); background: var(--px-accent-dim); }

/* ============================================================= sidebar === */
[data-testid="stSidebar"] {
  background: var(--px-bg-alt);
  border-right: 1px solid var(--px-line);
}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
  padding-top: 2.1rem;
}

[data-testid="stSidebar"] h1 {
  font-family: var(--px-font-mono);
  font-size: 0.72rem !important;
  font-weight: 600;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--px-faint);
  margin-bottom: 1rem;
}

/* ============================================================== tabs === */
/* Streamlit 1.63 renders tabs with React Aria, not BaseWeb: the list is a
   [role="tablist"] and each tab carries data-testid="stTab". */
.stTabs [role="tablist"] {
  gap: 4px;
  padding: 4px;
  border-radius: 11px;
  border: 1px solid var(--px-line);
  background: var(--px-bg-alt);
  display: inline-flex;
  flex-wrap: wrap;
}

/* Kill the default underline indicator. */
.stTabs [role="tablist"]::after,
.stTabs [role="tablist"]::before { display: none; }

[data-testid="stTab"] {
  height: auto;
  padding: 9px 18px;
  border-radius: 8px;
  color: var(--px-faint);
  cursor: pointer;
  border-bottom: none !important;
  transition: background 0.16s ease, color 0.16s ease;
}

[data-testid="stTab"] [data-testid="stMarkdownContainer"] p {
  font-family: var(--px-font-mono);
  font-size: 0.71rem;
  font-weight: 500;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  margin: 0;
}

[data-testid="stTab"]:hover {
  background: var(--px-surface);
  color: var(--px-dim);
}

[data-testid="stTab"][aria-selected="true"],
[data-testid="stTab"][data-selected="true"] {
  background: var(--px-surface-hi);
  color: var(--px-text);
  box-shadow: inset 0 0 0 1px var(--px-line);
}

[data-testid="stTab"][aria-selected="true"] [data-testid="stMarkdownContainer"] p {
  color: var(--px-text);
}

/* ============================================================ buttons === */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 9px;
  border: 1px solid var(--px-line);
  background: var(--px-surface);
  color: var(--px-text);
  font-family: var(--px-font-body);
  font-size: 0.85rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  padding: 0.5rem 1rem;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.1s ease;
}

.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--px-accent);
  background: var(--px-surface-hi);
  color: var(--px-text);
}

.stButton > button:active { transform: translateY(1px); }

/* Primary actions get the accent fill and a soft bloom. */
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primaryFormSubmit"] {
  background: linear-gradient(180deg, var(--px-accent-hi), var(--px-accent));
  border-color: transparent;
  color: #07090F;
  font-weight: 600;
  box-shadow: 0 6px 18px -8px rgba(77, 124, 254, 0.85);
}

.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primaryFormSubmit"]:hover {
  filter: brightness(1.07);
  border-color: transparent;
  color: #07090F;
}

/* ============================================================= inputs === */
[data-testid="stTextInputRootElement"],
[data-testid="stTextAreaRootElement"],
[data-testid="stSelectbox"] .react-aria-Group,
[data-testid="stMultiSelect"] .react-aria-Group {
  border-radius: 9px !important;
  border: 1px solid var(--px-line) !important;
  background: var(--px-bg-alt) !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stSelectbox"] .react-aria-Group:focus-within,
[data-testid="stMultiSelect"] .react-aria-Group:focus-within {
  border-color: var(--px-accent) !important;
  box-shadow: 0 0 0 3px var(--px-accent-dim) !important;
}

[data-testid="stTextInputField"],
[data-testid="stTextAreaRootElement"] textarea {
  background: transparent !important;
  color: var(--px-text) !important;
  font-family: var(--px-font-body) !important;
}

/* Widget labels become uppercase mono micro-type. */
[data-testid="stWidgetLabel"] p {
  font-family: var(--px-font-mono);
  font-size: 0.66rem !important;
  font-weight: 500;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--px-faint);
  margin-bottom: 0.3rem;
}

/* Multiselect tokens read as accent tags. */
[data-testid="stMultiSelectTagsContainer"] > * {
  background: var(--px-accent-dim) !important;
  border: 1px solid rgba(77, 124, 254, 0.34) !important;
  color: var(--px-accent-hi) !important;
  border-radius: 6px !important;
  font-family: var(--px-font-mono) !important;
  font-size: 0.7rem !important;
}

/* Dropdown surfaces float above the app; keep them on-palette. */
.react-aria-Popover, .react-aria-ListBox {
  background: var(--px-surface) !important;
  border: 1px solid var(--px-line) !important;
  border-radius: 10px !important;
}

.react-aria-ListBoxItem[data-focused="true"],
.react-aria-ListBoxItem[data-selected="true"] {
  background: var(--px-accent-dim) !important;
  color: var(--px-text) !important;
}

/* ============================================================ metrics === */
[data-testid="stMetric"] {
  border: 1px solid var(--px-line);
  border-radius: 12px;
  padding: 16px 18px;
  background: linear-gradient(165deg, var(--px-surface), var(--px-bg-alt));
  transition: border-color 0.18s ease;
}

[data-testid="stMetric"]:hover { border-color: rgba(77, 124, 254, 0.4); }

[data-testid="stMetricLabel"] p {
  font-family: var(--px-font-mono) !important;
  font-size: 0.64rem !important;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--px-faint) !important;
}

[data-testid="stMetricValue"] {
  font-family: var(--px-font-display) !important;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--px-text);
}

[data-testid="stMetricDelta"] {
  font-family: var(--px-font-mono) !important;
  font-size: 0.72rem !important;
}

/* ========================================================== containers === */
[data-testid="stExpander"] {
  border: 1px solid var(--px-line);
  border-radius: 10px;
  background: var(--px-bg-alt);
  overflow: hidden;
}

[data-testid="stExpander"] summary {
  padding: 11px 15px;
  font-size: 0.88rem;
  transition: background 0.15s ease;
}

[data-testid="stExpander"] summary:hover { background: var(--px-surface); }

[data-testid="stForm"] {
  border: 1px solid var(--px-line);
  border-radius: 12px;
  padding: 20px;
  background: var(--px-bg-alt);
}

/* Alerts: flat, left-marked, no candy fills. */
[data-testid="stAlertContainer"], [data-testid="stAlert"] {
  border-radius: 10px;
  border: 1px solid var(--px-line);
  border-left-width: 3px;
  background: var(--px-surface) !important;
  color: var(--px-dim) !important;
  font-size: 0.87rem;
}

/* ======================================================== chat messages === */
[data-testid="stChatMessage"] {
  background: transparent;
  border: 1px solid var(--px-line-soft);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 10px;
}

[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: var(--px-accent-dim);
  border-color: rgba(77, 124, 254, 0.26);
}

[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background: var(--px-bg-alt);
}

/* ============================================================ tables === */
[data-testid="stDataFrame"] {
  border: 1px solid var(--px-line);
  border-radius: 11px;
  overflow: hidden;
}

/* ========================================================== dividers === */
hr, [data-testid="stDivider"] hr {
  border: none;
  height: 1px;
  background: linear-gradient(90deg, var(--px-line), var(--px-line-soft) 60%, transparent);
  margin: 1.6rem 0;
}

/* =========================================================== progress === */
[data-testid="stProgress"] > div > div > div {
  background: linear-gradient(90deg, var(--px-accent), var(--px-volt));
}

/* ======================================================== empty state === */
.px-empty {
  border: 1px dashed var(--px-line);
  border-radius: 12px;
  padding: 30px 26px;
  text-align: center;
  background: linear-gradient(180deg, rgba(18, 22, 32, 0.5), transparent);
}

.px-empty-label {
  font-family: var(--px-font-mono);
  font-size: 0.64rem;
  font-weight: 500;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--px-accent);
  margin-bottom: 10px;
}

.px-empty-title {
  font-family: var(--px-font-display);
  font-size: 1.12rem;
  font-weight: 600;
  color: var(--px-text);
  margin-bottom: 7px;
  letter-spacing: -0.015em;
}

.px-empty-body {
  color: var(--px-faint);
  font-size: 0.87rem;
  line-height: 1.6;
  max-width: 46ch;
  margin: 0 auto;
}

.px-empty-body code {
  background: var(--px-surface);
  border: 1px solid var(--px-line);
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 0.8rem;
  color: var(--px-accent-hi);
}

/* ============================================================ mobile === */
@media (max-width: 640px) {
  .px-hero { padding: 22px 20px 20px; }
  .px-title { font-size: 2rem; }
  .stTabs [data-baseweb="tab"] { padding: 8px 12px; font-size: 0.64rem; }
}
"""


def inject() -> None:
    """Load fonts and the stylesheet. Call once, right after set_page_config."""
    st.markdown(
        f"<style>{_FONTS}{_CSS.replace('__VARS__', _vars())}</style>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ helpers
# Every caller-supplied string is escaped: these all render as raw HTML, and
# feature names and competitor names come from user input.


def hero(title: str, subtitle: str, eyebrow: str, stats, online: bool) -> None:
    """The masthead: eyebrow, wordmark, blurb, live status and counters.

    ``stats`` is a sequence of (value, label) pairs.
    """
    state = "live" if online else "down"
    status_text = "Agent online" if online else "LLM offline · fallback"

    # The eyebrow reads "PROXIMA // SUBTITLE"; the separator gets the accent.
    parts = [html.escape(piece.strip()) for piece in eyebrow.split("//")]
    eyebrow_html = "<span class='px-sep'>//</span>".join(parts)

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
