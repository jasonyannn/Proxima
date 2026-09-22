# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Tests for accounts, and for staying signed in across a refresh.

Run with:  python -m pytest tests -q      (or plain `python tests/test_accounts.py`)

Streamlit rebuilds session state on every browser connection, so without a
remembered session a page refresh signs you out. What matters most here is not
the happy path but the four ways the remembered session can be wrong — expired,
corrupt, missing, pointing at a deleted account — because every one of them runs
before the app has drawn anything, and a throw there is an app that will not
start at all.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

import accounts  # noqa: E402


class AccountsCase(unittest.TestCase):
    """Each test gets its own data directory; the real one is never touched."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._saved = (accounts.DATA, accounts.ACCOUNTS_DB, accounts.SESSION_FILE)
        accounts.DATA = root
        accounts.ACCOUNTS_DB = root / "accounts.db"
        accounts.SESSION_FILE = root / "session.json"
        accounts.init_db()

    def tearDown(self) -> None:
        accounts.DATA, accounts.ACCOUNTS_DB, accounts.SESSION_FILE = self._saved
        self._tmp.cleanup()

    def make_user(self, email: str = "a@example.com") -> dict:
        return accounts.create_account(email, "password-123", "Tester")


class TestRememberedSession(AccountsCase):
    def test_nothing_remembered_by_default(self) -> None:
        self.assertIsNone(accounts.remembered())

    def test_a_remembered_account_comes_back(self) -> None:
        user = self.make_user()
        accounts.remember(user["id"])

        restored = accounts.remembered()

        self.assertIsNotNone(restored)
        self.assertEqual(restored["id"], user["id"])
        self.assertEqual(restored["email"], user["email"])

    def test_it_survives_repeated_reads(self) -> None:
        # Every refresh is another read; one must not consume it.
        user = self.make_user()
        accounts.remember(user["id"])

        for _ in range(3):
            self.assertIsNotNone(accounts.remembered())

    def test_forget_signs_out_for_good(self) -> None:
        user = self.make_user()
        accounts.remember(user["id"])
        accounts.forget()

        self.assertIsNone(accounts.remembered())
        self.assertFalse(accounts.SESSION_FILE.exists())

    def test_forget_is_safe_when_nothing_is_stored(self) -> None:
        accounts.forget()  # must not raise
        self.assertIsNone(accounts.remembered())

    def test_an_expired_session_is_refused_and_cleared(self) -> None:
        user = self.make_user()
        accounts.SESSION_FILE.write_text(
            json.dumps(
                {
                    "user_id": user["id"],
                    "expires": (datetime.now() - timedelta(days=1)).isoformat(),
                }
            )
        )

        self.assertIsNone(accounts.remembered())
        self.assertFalse(accounts.SESSION_FILE.exists())

    def test_an_unexpired_session_is_honoured(self) -> None:
        user = self.make_user()
        accounts.SESSION_FILE.write_text(
            json.dumps(
                {
                    "user_id": user["id"],
                    "expires": (datetime.now() + timedelta(minutes=1)).isoformat(),
                }
            )
        )

        self.assertIsNotNone(accounts.remembered())

    def test_remember_sets_an_expiry_in_the_future(self) -> None:
        user = self.make_user()
        accounts.remember(user["id"])

        stored = json.loads(accounts.SESSION_FILE.read_text())
        self.assertGreater(datetime.fromisoformat(stored["expires"]), datetime.now())

    def test_a_deleted_account_does_not_sign_in(self) -> None:
        # The file outlives the account it names.
        accounts.remember(4242)

        self.assertIsNone(accounts.remembered())
        self.assertFalse(accounts.SESSION_FILE.exists())

    def test_rubbish_never_reaches_the_app(self) -> None:
        # Whatever is in the file, the answer is "sign in", never a traceback.
        for junk in ("{corrupt", "", "null", "[]", '{"user_id": "x"}', '{"expires": 1}'):
            with self.subTest(junk=junk):
                accounts.SESSION_FILE.write_text(junk)
                self.assertIsNone(accounts.remembered())
                self.assertFalse(accounts.SESSION_FILE.exists())


class TestLookupById(AccountsCase):
    def test_finds_an_account(self) -> None:
        user = self.make_user()
        self.assertEqual(accounts.by_id(user["id"])["email"], user["email"])

    def test_returns_none_for_a_stranger(self) -> None:
        self.assertIsNone(accounts.by_id(9999))


class TestSignIn(AccountsCase):
    """The existing path, pinned so the session work above cannot break it."""

    def test_correct_password_authenticates(self) -> None:
        user = self.make_user()
        self.assertEqual(accounts.authenticate(user["email"], "password-123")["id"], user["id"])

    def test_wrong_password_is_refused(self) -> None:
        self.make_user()
        with self.assertRaises(accounts.AccountError):
            accounts.authenticate("a@example.com", "not-the-password")


if __name__ == "__main__":
    unittest.main()
