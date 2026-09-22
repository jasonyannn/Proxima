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
import report_blocks  # noqa: E402
import visuals  # noqa: E402
from database import DatabaseManager  # noqa: E402
from fixtures import seed  # noqa: E402
from reportlab.graphics.shapes import Drawing  # noqa: E402
from reportlab.platypus import KeepTogether, Paragraph, Table  # noqa: E402


def flatten(flowables):
    """KeepTogether hides its contents from a plain type check."""
    out = []
    for f in flowables:
        out.extend(flatten(f._content)) if isinstance(f, KeepTogether) else out.append(f)
    return out


def kinds(flowables):
    return [type(f).__name__ for f in flatten(flowables)]

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



CHART = (
    '```proxima-chart\n'
    '{"kind": "bar", "title": "Competitor Analysis", "unit": "%", "data": '
    '[{"label": "Contract Management Platforms", "value": 60}, '
    '{"label": "Legal Document Platforms", "value": 40}], "note": "Estimates."}\n'
    '```'
)


class TestTypedBlocks(unittest.TestCase):
    """The blocks the app draws must be drawn here too, not dumped as JSON.

    This is the regression the whole section exists for: the chart directive
    was reaching the page as its own source code.
    """

    def test_a_chart_block_becomes_a_drawing(self) -> None:
        out = report.markdown(CHART)

        self.assertIn("Drawing", kinds(out))
        # And the spec itself must not survive as visible text.
        rendered = " ".join(f.text for f in flatten(out) if hasattr(f, "text"))
        self.assertNotIn("proxima-chart", rendered)
        self.assertNotIn('"kind"', rendered)

    def test_the_title_and_note_come_with_it(self) -> None:
        rendered = " ".join(
            f.text for f in flatten(report.markdown(CHART)) if hasattr(f, "text")
        )
        self.assertIn("Competitor Analysis", rendered)
        self.assertIn("Estimates.", rendered)

    def test_prose_around_a_chart_survives(self) -> None:
        out = report.markdown(f"Before the chart.\n\n{CHART}\n\nAfter the chart.")
        rendered = " ".join(f.text for f in flatten(out) if hasattr(f, "text"))
        self.assertIn("Before the chart.", rendered)
        self.assertIn("After the chart.", rendered)
        self.assertIn("Drawing", kinds(out))

    def test_every_chart_kind_draws(self) -> None:
        for kind in ("bar", "column", "line", "area"):
            block = (
                '```proxima-chart\n'
                f'{{"kind": "{kind}", "data": [{{"label": "A", "value": 1}}, '
                '{"label": "B", "value": 2}]}\n```'
            )
            with self.subTest(kind=kind):
                self.assertIn("Drawing", kinds(report.markdown(block)))

    def test_a_grouped_chart_draws_one_series_per_group(self) -> None:
        block = (
            '```proxima-chart\n'
            '{"kind": "column", "data": ['
            '{"label": "Concept", "value": 62, "series": "Mine"}, '
            '{"label": "Concept", "value": 44, "series": "Rival"}]}\n```'
        )
        drawing = [f for f in flatten(report.markdown(block)) if isinstance(f, Drawing)]
        self.assertEqual(len(drawing), 1)

    def test_horizontal_bars_read_top_down(self) -> None:
        # reportlab stacks categories bottom-up, so the order is reversed on the
        # way in. First row in the spec must be the top bar on the page.
        spec = visuals.chart_spec(
            '{"kind": "bar", "data": [{"label": "First", "value": 1}, '
            '{"label": "Second", "value": 2}]}'
        )
        drawing = report_blocks._chart_drawing(spec)
        chart = drawing.contents[0]
        self.assertEqual(chart.categoryAxis.categoryNames[-1], "First")

    def test_a_table_block_becomes_a_table(self) -> None:
        block = (
            '```proxima-table\n'
            '{"title": "Overlap", "columns": ["Rival", "Overlap"], '
            '"rows": [["Northwind", "18%"]]}\n```'
        )
        out = report.markdown(block)
        self.assertIn("Table", kinds(out))
        rendered = " ".join(f.text for f in flatten(out) if hasattr(f, "text"))
        self.assertIn("Overlap", rendered)

    def test_a_mermaid_block_keeps_its_source(self) -> None:
        out = report.markdown("```mermaid\nflowchart TD\n  A --> B\n```")
        rendered = " ".join(f.text for f in flatten(out) if hasattr(f, "text"))
        self.assertIn("Diagram", rendered)
        self.assertIn("Table", kinds(out))  # the fenced source block

    def test_a_malformed_chart_degrades_to_its_source(self) -> None:
        # visuals rejects it; the reader still gets to see what was meant,
        # with the reason, exactly as the app does.
        out = report.markdown('```proxima-chart\n{"kind": "bar", "data": []}\n```')
        rendered = " ".join(f.text for f in flatten(out) if hasattr(f, "text"))
        self.assertIn("Unrendered block", rendered)
        self.assertIn("Table", kinds(out))

    def test_an_ordinary_fence_is_still_code(self) -> None:
        out = report.markdown("```\nplain code\n```")
        self.assertEqual(kinds(out), ["Table"])

    def test_a_chart_inside_an_ip_report_renders(self) -> None:
        # The blocks appear in stored reports too, not only the transcript.
        db = fresh_db()
        db.create_ip_assessment("Engine", "Compares clauses.", "Medium", 46.0, CHART)
        pdf = report.build(db, PROJECT, [])
        self.assertTrue(pdf.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
