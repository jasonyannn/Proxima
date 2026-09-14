"""Tests for the competitor and copyright analysers.

Run with:  python -m pytest tests -q      (or plain `python tests/test_analysis.py`)

The labelled pairs in TestCalibration are the evidence behind the MATCH_STRONG /
MATCH_PARTIAL constants in competitors.py. If you tune the similarity metric,
these tests tell you whether you actually improved it or just moved the numbers.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

from competitors import (  # noqa: E402
    CompetitorAnalyzer,
    MATCH_PARTIAL,
    MATCH_STRONG,
    STATUS_MATCH,
    classify,
)
from copyright_analyzer import CopyrightAnalyzer  # noqa: E402
from database import DatabaseManager  # noqa: E402
from fixtures import seed  # noqa: E402
from textsim import (  # noqa: E402
    concept_similarity,
    expression_similarity,
    longest_common_phrase,
    name_similarity,
)

# Pairs that describe the same job, in different words.
SAME_JOB = [
    ("Dark mode", "Dark theme"),
    (
        "Sentiment inference. Infers whether feedback is positive, neutral or negative.",
        "Sentiment analysis. Classifies feedback as positive, neutral or negative.",
    ),
    ("Roadmap timeline", "Product roadmap planning view"),
    ("Impact scoring", "Prioritisation scoring model"),
    ("Executive dashboards", "Leadership reporting dashboard"),
    ("Theme clustering", "Feedback theme grouping"),
    ("AI summary digest", "Generated weekly summary"),
    ("SSO", "Single sign-on authentication"),
]

# Pairs that are genuinely unrelated.
DIFFERENT_JOB = [
    ("Dark mode", "Git integration"),
    ("Sentiment analysis", "Sprint cycles"),
    ("Roadmap timeline", "Keyboard-first navigation"),
    ("Impact scoring", "Dark mode"),
    ("Executive dashboards", "SSO and audit log"),
    (
        "Local-first LLM. Runs against a locally hosted model.",
        "Idea portal. Public portal where customers vote.",
    ),
]


def fresh_db() -> DatabaseManager:
    path = os.path.join(tempfile.mkdtemp(), "nested", "test.db")
    db = DatabaseManager(path)
    db.init_db()
    return db


class TestTextSim(unittest.TestCase):
    def test_identical_text_scores_one(self):
        self.assertEqual(concept_similarity("Dark mode", "Dark mode"), 1.0)
        self.assertEqual(expression_similarity("Dark mode", "Dark mode"), 1.0)

    def test_empty_text_is_safe(self):
        self.assertEqual(concept_similarity("", "Dark mode"), 0.0)
        self.assertEqual(expression_similarity("", ""), 0.0)
        self.assertEqual(name_similarity("", "x"), 0.0)
        self.assertEqual(longest_common_phrase("", "anything"), "")

    def test_synonyms_bridge_vocabulary_gap(self):
        # The whole point of the synonym layer.
        self.assertGreaterEqual(concept_similarity("Dark mode", "Dark theme"), MATCH_STRONG)

    def test_acronyms_expand(self):
        self.assertGreaterEqual(
            concept_similarity("SSO", "Single sign-on authentication"), MATCH_STRONG
        )

    def test_concept_and_expression_are_independent(self):
        """Same idea, totally different words -> high concept, low expression."""
        a = "Dark mode"
        b = "Night-time colour theme for reduced eye strain"
        self.assertGreater(concept_similarity(a, b), expression_similarity(a, b))

    def test_verbatim_run_is_detected(self):
        a = "Collects customer messages from support tools and surveys into one queue"
        b = "Our product collects customer messages from support tools and surveys too"
        phrase = longest_common_phrase(a, b)
        self.assertGreaterEqual(len(phrase.split()), 6)


class TestCalibration(unittest.TestCase):
    """The evidence behind the MATCH_STRONG / MATCH_PARTIAL thresholds."""

    def test_same_job_pairs_score_above_strong_threshold(self):
        failures = [
            (a, b, concept_similarity(a, b))
            for a, b in SAME_JOB
            if concept_similarity(a, b) < MATCH_STRONG
        ]
        self.assertEqual(failures, [], f"same-job pairs fell below threshold: {failures}")

    def test_unrelated_pairs_score_below_partial_threshold(self):
        failures = [
            (a, b, concept_similarity(a, b))
            for a, b in DIFFERENT_JOB
            if concept_similarity(a, b) >= MATCH_PARTIAL
        ]
        self.assertEqual(failures, [], f"unrelated pairs scored too high: {failures}")

    def test_thresholds_sit_in_the_gap_between_clusters(self):
        worst_match = min(concept_similarity(a, b) for a, b in SAME_JOB)
        best_nonmatch = max(concept_similarity(a, b) for a, b in DIFFERENT_JOB)
        self.assertLess(
            best_nonmatch,
            MATCH_STRONG,
            "threshold no longer separates the two clusters",
        )
        self.assertLessEqual(MATCH_STRONG, worst_match)

    def test_classify_boundaries(self):
        self.assertEqual(classify(MATCH_STRONG), STATUS_MATCH)
        self.assertEqual(classify(MATCH_PARTIAL), "Partial")
        self.assertEqual(classify(0.0), "Gap")


class TestCompetitorAnalyzer(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        seed(self.db)
        self.analyzer = CompetitorAnalyzer(self.db)

    def test_seed_is_idempotent(self):
        before = len(self.db.list_competitor_features())
        seed(self.db)
        self.assertEqual(len(self.db.list_competitor_features()), before)

    def test_matrix_covers_every_feature_and_competitor(self):
        names = [c["name"] for c in self.db.list_competitors()]
        matrix = self.analyzer.build_matrix()
        self.assertEqual(len(matrix), len(self.db.list_features()))
        for row in matrix:
            self.assertEqual(set(row.per_competitor.keys()), set(names))

    def test_sentiment_feature_matches_rival_sentiment_feature(self):
        """The end-to-end check that motivated the synonym layer."""
        matrix = self.analyzer.build_matrix()
        row = next(r for r in matrix if "Sentiment" in r.feature)
        cell = row.per_competitor["Vellum Insights"]
        self.assertEqual(cell["status"], STATUS_MATCH)
        self.assertEqual(cell["matched_feature"], "Sentiment analysis")

    def test_gap_analysis_finds_unanswered_rival_features(self):
        gaps = self.analyzer.gap_analysis()
        missing = {g["feature"] for g in gaps["we_are_missing"]}
        # We have no roadmap or git features at all.
        self.assertIn("Git integration", missing)
        for gap in gaps["we_are_missing"]:
            self.assertTrue(gap["competitors"])
            self.assertIn(
                gap["pressure"], {"Table stakes", "Emerging", "Single-vendor bet"}
            )

    def test_differentiators_are_not_also_gaps(self):
        gaps = self.analyzer.gap_analysis()
        differentiators = {d["feature"] for d in gaps["our_differentiators"]}
        parity = {p["feature"] for p in gaps["parity"]}
        self.assertEqual(differentiators & parity, set())

    def test_scores_are_sorted_by_threat(self):
        scores = self.analyzer.score_competitors()
        rank = {"High": 0, "Moderate": 1, "Low": 2}
        ranks = [rank[s.threat] for s in scores]
        self.assertEqual(ranks, sorted(ranks))
        for score in scores:
            self.assertGreaterEqual(score.overlap, 0.0)
            self.assertLessEqual(score.overlap, 1.0)

    def test_empty_workspace_does_not_crash(self):
        empty = CompetitorAnalyzer(fresh_db())
        self.assertEqual(empty.build_matrix(), [])
        self.assertEqual(empty.score_competitors(), [])
        gaps = empty.gap_analysis()
        self.assertEqual(gaps["we_are_missing"], [])


class TestCopyrightAnalyzer(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        seed(self.db)
        self.analyzer = CopyrightAnalyzer(self.db)
        self.rivals = self.db.list_competitor_features()

    def test_unrelated_feature_is_low_risk(self):
        report = self.analyzer.analyze(
            "Offline mobile sync",
            "Queues edits made on a phone with no signal and reconciles them later.",
            self.rivals,
        )
        self.assertEqual(report.risk_level, "Low")

    def test_verbatim_copy_is_high_risk(self):
        """Copying a rival's description word-for-word must be flagged."""
        rival = next(f for f in self.rivals if f["name"] == "Feedback inbox")
        report = self.analyzer.analyze(
            "Feedback inbox", rival["description"], self.rivals
        )
        self.assertIn(report.risk_level, ("Elevated", "High"))
        self.assertTrue(
            any(f.kind == "copyright" and f.severity == "High" for f in report.findings)
        )

    def test_same_idea_different_words_is_not_a_copyright_alarm(self):
        """The core principle: ideas aren't protected, expression is."""
        report = self.analyzer.analyze(
            "Mood detection",
            "Works out how happy or unhappy each piece of customer input sounds.",
            self.rivals,
        )
        self.assertIn(report.risk_level, ("Low", "Moderate"))
        # It should still notice the functional overlap, as a patent-flavoured note.
        kinds = {f.kind for f in report.findings}
        self.assertIn("patent", kinds)
        self.assertFalse(
            any(f.kind == "copyright" and f.severity == "High" for f in report.findings)
        )

    def test_copy_intent_language_is_flagged(self):
        report = self.analyzer.analyze(
            "Roadmap view",
            "Build a pixel-perfect clone of Northwind PM's roadmap timeline.",
            self.rivals,
        )
        self.assertTrue(
            any(f.kind == "practice" and f.severity == "High" for f in report.findings)
        )

    def test_protected_asset_mention_is_flagged(self):
        report = self.analyzer.analyze(
            "New empty states",
            "Reuse their icon set and illustration artwork for the empty states.",
            self.rivals,
        )
        self.assertTrue(any(f.kind == "copyright" for f in report.findings))

    def test_score_is_bounded_and_level_agrees(self):
        for title, desc in [
            ("A", ""),
            ("Feedback inbox", "Collects customer messages from support tools."),
            ("Clone it", "Copy their entire source code and stylesheet verbatim."),
        ]:
            report = self.analyzer.analyze(title, desc, self.rivals)
            self.assertGreaterEqual(report.risk_score, 0.0)
            self.assertLessEqual(report.risk_score, 100.0)
            self.assertIn(report.risk_level, ("Low", "Moderate", "Elevated", "High"))

    def test_report_serialises_to_json(self):
        import json

        report = self.analyzer.analyze("Dark mode", "A dark colour theme.", self.rivals)
        payload = json.loads(report.to_json())
        self.assertEqual(payload["feature_title"], "Dark mode")
        self.assertIn("disclaimer", payload)
        for match in payload["matches"]:
            self.assertIn("relationship", match)

    def test_no_competitor_data_is_handled(self):
        report = CopyrightAnalyzer(fresh_db()).analyze("Anything", "Some description", [])
        self.assertEqual(report.risk_level, "Low")
        self.assertEqual(report.matches, [])
        self.assertTrue(report.recommendations)

    def test_recommendations_always_present(self):
        report = self.analyzer.analyze("Dark mode", "A dark colour theme.", self.rivals)
        self.assertTrue(report.recommendations)


class TestDatabase(unittest.TestCase):
    def test_creates_missing_directory(self):
        """Regression: the default data/ directory did not exist and sqlite failed."""
        path = os.path.join(tempfile.mkdtemp(), "a", "b", "c", "product.db")
        db = DatabaseManager(path)
        db.init_db()
        self.assertTrue(os.path.exists(path))

    def test_upsert_competitor_updates_in_place(self):
        db = fresh_db()
        first = db.upsert_competitor("Acme", website="https://a.example")
        second = db.upsert_competitor("Acme", pricing="$10")
        self.assertEqual(first, second)
        self.assertEqual(len(db.list_competitors()), 1)
        record = db.list_competitors()[0]
        # The original website survives an update that didn't mention it.
        self.assertEqual(record["website"], "https://a.example")
        self.assertEqual(record["pricing"], "$10")

    def test_deleting_competitor_removes_its_features(self):
        db = fresh_db()
        cid = db.upsert_competitor("Acme")
        db.create_competitor_feature(cid, "Thing", "does a thing")
        db.delete_competitor(cid)
        self.assertEqual(db.list_competitor_features(), [])

    def test_ip_assessments_round_trip(self):
        db = fresh_db()
        db.create_ip_assessment("F", "d", "Low", 3.0, "{}")
        rows = db.list_ip_assessments()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["risk_level"], "Low")


if __name__ == "__main__":
    unittest.main(verbosity=2)
