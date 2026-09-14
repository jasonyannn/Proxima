"""Local accounts: sign up, sign in, and keep each person's work apart.

Everything here stays on this machine. There is no identity provider and no
network call — an account is a row in a SQLite file beside the workspaces, and
signing in only decides which folder of chats you are shown.

Passwords are stored as PBKDF2-HMAC-SHA256 over a per-user random salt, never
in the clear and never reversibly. That is the floor for storing a password at
all; it is not a substitute for a real identity system if this ever leaves one
laptop and faces the internet.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"
ACCOUNTS_DB = DATA / "accounts.db"

# Deliberately slow: the whole point of a KDF is that guessing costs something.
ITERATIONS = 240_000

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MIN_PASSWORD = 8


class AccountError(Exception):
    """Something the person signing up or in needs to be told about."""


def _connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(ACCOUNTS_DB))
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with closing(_connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP
            )
            """
        )
        connection.commit()


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "name": row["name"] or row["email"].split("@")[0],
    }


def create_account(email: str, password: str, name: str = "") -> dict[str, Any]:
    """Register someone. Raises AccountError with a message they can act on."""
    email = (email or "").strip()
    name = (name or "").strip()

    if not EMAIL.match(email):
        raise AccountError("That does not look like an email address.")
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters for the password.")

    init_db()
    salt = os.urandom(16)
    try:
        with closing(_connect()) as connection:
            cursor = connection.execute(
                "INSERT INTO account (email, name, salt, password_hash) VALUES (?, ?, ?, ?)",
                (email, name or None, salt, _hash(password, salt)),
            )
            connection.commit()
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        raise AccountError("There is already an account with that email.") from None

    return {"id": user_id, "email": email, "name": name or email.split("@")[0]}


def authenticate(email: str, password: str) -> dict[str, Any]:
    """Check a password. Same error either way — which half was wrong is not
    the signer-in's business to learn, and not a stranger's."""
    init_db()
    email = (email or "").strip()

    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM account WHERE email = ?", (email,)
        ).fetchone()

        if row is None:
            # Spend the time anyway: answering instantly for unknown addresses
            # is how a login form tells you which emails are registered.
            _hash(password or "", os.urandom(16))
            raise AccountError("Email or password is not right.")

        if not hmac.compare_digest(bytes(row["password_hash"]), _hash(password or "", bytes(row["salt"]))):
            raise AccountError("Email or password is not right.")

        connection.execute(
            "UPDATE account SET last_seen = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), row["id"]),
        )
        connection.commit()
        return _row_to_user(row)


def count() -> int:
    """How many accounts exist — the landing page greets the first one."""
    init_db()
    with closing(_connect()) as connection:
        return int(connection.execute("SELECT COUNT(*) AS n FROM account").fetchone()["n"])
