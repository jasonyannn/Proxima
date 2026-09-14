"""The page you meet before signing in.

Two jobs, in this order: say what Proxima is to someone who has never seen it,
and get them into it. Everything below the fold is there to answer "should I
type my first message", not to decorate.
"""
from __future__ import annotations

import base64
import html
import pathlib
from functools import lru_cache

import streamlit as st

try:
    from . import accounts, theme
except ImportError:  # pragma: no cover
    import accounts, theme


@lru_cache(maxsize=4)
def _data_uri(path: str) -> str:
    try:
        return "data:image/png;base64," + base64.b64encode(
            pathlib.Path(path).read_bytes()
        ).decode()
    except OSError:
        return ""


PITCH = [
    (
        "Talk, don't fill in forms",
        "Describe what your customers said in the words they said it. Proxima "
        "turns it into a structured product decision — issue, recommendation, "
        "reasoning, next steps.",
    ),
    (
        "Nothing is filed behind your back",
        "It reads your message for features, bugs and rivals worth keeping, and "
        "offers them under your message. One press files one. Undo is next to it.",
    ),
    (
        "Know where you stand",
        "Name a competitor and Proxima fills in what it knows of their product, "
        "then shows the overlap, the gaps you need to close, and the ground only "
        "you hold.",
    ),
    (
        "Check the idea before you build it",
        "The copyright analyser separates the idea from the way it is expressed, "
        "and tells you which half is the risk.",
    ),
]


def _styles() -> None:
    st.markdown(
        """
        <style>
        .px-land {
          position: relative;
          border: 1px solid var(--px-line);
          border-radius: 16px;
          padding: 54px 46px 46px;
          margin-bottom: 26px;
          overflow: hidden;
          background:
            radial-gradient(900px 340px at 78% -25%, rgba(77, 124, 254, 0.20), transparent 62%),
            radial-gradient(620px 280px at 4% 120%, rgba(200, 249, 76, 0.06), transparent 60%),
            linear-gradient(160deg, var(--px-surface) 0%, var(--px-bg-alt) 100%);
        }
        .px-land img { height: 62px; width: auto; margin-bottom: 26px; }
        .px-land h1 {
          font-family: var(--px-font-display);
          font-size: clamp(2.1rem, 5vw, 3.4rem);
          font-weight: 700;
          line-height: 1.02;
          letter-spacing: -0.035em;
          margin: 0 0 16px;
          max-width: 22ch;
          background: linear-gradient(96deg, #FFFFFF 10%, #C3D2F5 55%, var(--px-accent-hi) 100%);
          -webkit-background-clip: text;
          background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .px-land p.lede {
          color: var(--px-dim);
          font-size: 1.05rem;
          line-height: 1.6;
          max-width: 56ch;
          margin: 0;
        }
        .px-land .px-eyebrow { margin-bottom: 18px; display: block; }

        .px-card {
          border: 1px solid var(--px-line);
          border-radius: 12px;
          padding: 20px 22px;
          height: 100%;
          background: linear-gradient(165deg, var(--px-surface), var(--px-bg-alt));
        }
        .px-card h3 {
          font-family: var(--px-font-display);
          font-size: 1rem;
          font-weight: 600;
          margin: 0 0 8px;
          letter-spacing: -0.01em;
        }
        .px-card p {
          color: var(--px-faint);
          font-size: 0.87rem;
          line-height: 1.6;
          margin: 0;
        }
        .px-local {
          display: inline-flex;
          align-items: center;
          gap: 9px;
          margin-top: 26px;
          padding: 9px 15px;
          border: 1px solid rgba(200, 249, 76, 0.28);
          border-radius: 999px;
          background: rgba(200, 249, 76, 0.05);
          font-family: var(--px-font-mono);
          font-size: 0.66rem;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--px-volt);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _hero(mark: str) -> None:
    logo = _data_uri(mark)
    st.markdown(
        f"""
        <div class="px-land">
          {'<img src="' + logo + '" alt="Proxima">' if logo else ''}
          <span class="px-eyebrow">Proxima<span class='px-sep'>//</span>Product intelligence system</span>
          <h1>Your customers already told you what to build.</h1>
          <p class="lede">
            Proxima is a product manager that listens. Paste the raw feedback,
            argue with it about priorities, and walk away with a decision you can
            defend — plus a backlog, a competitive read and an IP check that you
            chose to keep.
          </p>
          <div class="px-local"><span>●</span> Runs on your machine · your own model · no data leaves</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _pitch() -> None:
    for row in (PITCH[:2], PITCH[2:]):
        for column, (title, body) in zip(st.columns(len(row), gap="medium"), row):
            column.markdown(
                f"""<div class="px-card"><h3>{html.escape(title)}</h3>
                <p>{html.escape(body)}</p></div>""",
                unsafe_allow_html=True,
            )
        st.write("")


def _gate() -> dict | None:
    """Sign-in and sign-up. Returns the signed-in user, or None."""
    first_run = accounts.count() == 0
    theme.section("Get started" if first_run else "Sign in", index="01")

    if first_run:
        st.caption(
            "No accounts on this machine yet — the first one you make is yours. "
            "Accounts exist to keep separate people's chats and workspaces apart; "
            "everything stays in this folder."
        )

    sign_in, sign_up = st.tabs(["Sign in", "Create account"])

    with sign_in:
        with st.form("sign_in", clear_on_submit=False):
            email = st.text_input("Email", key="in_email")
            password = st.text_input("Password", type="password", key="in_password")
            if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                try:
                    return accounts.authenticate(email, password)
                except accounts.AccountError as exc:
                    st.error(str(exc))

    with sign_up:
        with st.form("sign_up", clear_on_submit=False):
            name = st.text_input("Name", key="up_name", placeholder="Optional")
            email = st.text_input("Email", key="up_email")
            password = st.text_input(
                "Password",
                type="password",
                key="up_password",
                help=f"At least {accounts.MIN_PASSWORD} characters.",
            )
            confirm = st.text_input("Confirm password", type="password", key="up_confirm")
            if st.form_submit_button("Create account", type="primary", use_container_width=True):
                if password != confirm:
                    st.error("Those two passwords are not the same.")
                else:
                    try:
                        return accounts.create_account(email, password, name)
                    except accounts.AccountError as exc:
                        st.error(str(exc))

    return None


def render(mark: str) -> dict | None:
    """Draw the landing page. Returns the user if they just signed in."""
    _styles()
    _hero(mark)

    left, right = st.columns([3, 2], gap="large")
    with left:
        _pitch()
    with right:
        user = _gate()

    st.caption(
        "Proxima talks to a model running locally through Ollama. Nothing you "
        "type is sent to an API, and your password is stored only as a salted "
        "PBKDF2 hash on this machine."
    )
    return user
