# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Tests for the PDF workspace report.

Run with:  python -m pytest tests -q      (or plain `python tests/test_report.py`)

Two things are worth holding still here. The markdown converter, because the
agent writes markdown and reportlab parses its own mini-HTML — an unescaped
``<`` in a feature description takes the whole document down. And the empty
cases, because a report that renders only when the workspace is full is a
report that fails the first time anyone tries it.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

import report  # noqa: E402
from database import DatabaseManager  # noqa: E402
from fixtures import seed  # noqa: E402
from reportlab.platypus import Paragraph, Table  # noqa: E402

PROJECT = {"name": "Privacy Lens App", "brief": "Red and green flags for terms and conditions."}


def fresh_db() -> DatabaseManager:
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    db = DatabaseManager(path)
    db.init_db()
    return db


def text_of(flowable) -> str:
    return getattr(flowable, "text", "")


class TestMarkdown(unittest.TestCase):
    def test_bold_and_italic_become_tags(self) -> None:
        out = report.markdown("A **strong** and *soft* point")
        self.assertIn("<b>strong</b>", text_of(out[0]))
        self.assertIn("<i>soft</i>", text_of(out[0]))

    def test_angle_brackets_are_escaped(self) -> None:
        # The failure this prevents: reportlab reads <script> as markup it does
        # not know and raises, taking the whole export with it.
        out = report.markdown("Compare <script> & <b>tags</b> in a clause")
        rendered = text_of(out[0])
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&amp;", rendered)

    def test_code_spans_survive_asterisks(self) -> None:
        out = report.markdown("Run `a * b` then **stop**")
        rendered = text_of(out[0])
        self.assertIn("Courier", rendered)
        self.assertIn("a * b", rendered)
        self.assertIn("<b>stop</b>", rendered)

    def test_bullets_and_numbers_get_bullet_text(self) -> None:
        out = report.markdown("- first\n- second\n\n1. one\n2. two")
        self.assertEqual(len(out), 4)
        self.assertEqual([f.bulletText for f in out], ["•", "•", "1.", "2."])

    def test_headings_use_the_heading_style(self) -> None:
        out = report.markdown("## Finding\n\nBody text")
        self.assertEqual(out[0].style.name, "heading")
        self.assertEqual(out[1].style.name, "body")

    def test_a_pipe_table_becomes_a_table(self) -> None:
        out = report.markdown("| Rival | Overlap |\n|---|---|\n| Northwind | 18% |")
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], Table)

    def test_a_lone_pipe_is_not_a_table(self) -> None:
        # No divider row, so this is prose with a bar in it.
        out = report.markdown("Costs $5 | maybe $6")
        self.assertIsInstance(out[0], Paragraph)

    def test_fenced_code_becomes_one_block(self) -> None:
        out = report.markdown("Before\n```\nline one\nline two\n```\nAfter")
        self.assertIsInstance(out[1], Table)
        self.assertEqual(len(out), 3)

    def test_empty_text_produces_nothing(self) -> None:
        self.assertEqual(report.markdown(""), [])
        self.assertEqual(report.markdown(None), [])


class TestEmptiness(unittest.TestCase):
    def test_a_fresh_workspace_is_empty(self) -> None:
        self.assertTrue(report.is_empty(fresh_db(), []))

    def test_one_feature_is_not_empty(self) -> None:
        db = fresh_db()
        db.create_feature("Fairness score")
        self.assertFalse(report.is_empty(db, []))

    def test_a_chat_alone_is_not_empty(self) -> None:
        # Worth exporting: the conversation is the reasoning, even before
        # anything has been filed off it.
        db = fresh_db()
        self.assertFalse(report.is_empty(db, [{"user": "hello", "agent": "hi"}]))

    def test_blank_messages_do_not_count(self) -> None:
        db = fresh_db()
        self.assertTrue(report.is_empty(db, [{"user": "", "agent": None}]))


class TestBuild(unittest.TestCase):
    def test_a_full_workspace_renders(self) -> None:
        db = fresh_db()
        seed(db)
        sprint = db.create_sprint("Sprint 1", "Ship it", "2026-09-01", "2026-09-14", "Active")
        db.create_ticket("Parse T&Cs", "PDF and pasted text.", "In Progress", "High", 5, sprint)
        db.create_ticket("Flag UI", None, "Backlog", "Medium", 3, None)
        db.create_ip_assessment(
            "Clause engine",
            "Compares clauses.",
            "Medium",
            46.0,
            "## Finding\n\n**Conceptual** overlap.\n\n| Rival | Overlap |\n|---|---|\n| N | 18% |",
        )
        db.create_feedback("support", "Users want a score they trust.", "positive")
        db.create_bug("Upload fails", "Timeout.", "high", "open")

        pdf = report.build(db, PROJECT, [{"user": "Why?", "agent": "- Because\n- Of this"}])

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertGreater(len(pdf), 10_000)

    def test_an_empty_workspace_still_renders(self) -> None:
        # The report must not need data to exist. Every section says so instead.
        pdf = report.build(fresh_db(), PROJECT, [])

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))

    def test_no_project_still_renders(self) -> None:
        pdf = report.build(fresh_db(), None, [])
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_hostile_text_does_not_break_the_document(self) -> None:
        db = fresh_db()
        db.create_feature(
            "Diff <script>alert(1)</script> & co",
            "Compares <b>unescaped</b> markup & ampersands — also `code`.",
        )
        db.upsert_competitor("A & B <Ltd>", "https://example.com", "Sells <things>", "$1", "Note & note")

        pdf = report.build(db, {"name": "A & B <Ltd>"}, [{"user": "<hi>", "agent": "**<bye>**"}])

        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_a_long_transcript_paginates(self) -> None:
        db = fresh_db()
        messages = [
            {"user": f"Question {n}", "agent": "Answer paragraph. " * 40} for n in range(25)
        ]
        pdf = report.build(db, PROJECT, messages)

        pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
        self.assertGreater(pages, 3)


class TestFilename(unittest.TestCase):
    def test_slugs_the_project_name_and_dates_it(self) -> None:
        name = report.filename(PROJECT, datetime(2026, 9, 22))
        self.assertEqual(name, "privacy-lens-app-report-2026-09-22.pdf")

    def test_falls_back_when_there_is_no_project(self) -> None:
        self.assertTrue(report.filename(None, datetime(2026, 9, 22)).endswith(".pdf"))

    def test_punctuation_never_reaches_the_filename(self) -> None:
        name = report.filename({"name": "A & B / C: “D”"}, datetime(2026, 9, 22))
        self.assertEqual(name, "a-b-c-d-report-2026-09-22.pdf")


if __name__ == "__main__":
    unittest.main()
