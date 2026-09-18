# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Tests for turning a model's answer into charts, tables and diagrams.

The thing worth guarding is not the happy path — it is that a *bad* block never
costs the user their answer. A local model emits trailing commas, writes "62%"
where a number belongs, and occasionally opens a fence it never closes. Every
one of those has to degrade to visible text, because the alternative is a
traceback in the middle of a reply the user was reading.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

import visuals  # noqa: E402


def fence(tag, body):
    return f"```{tag}\n{body}\n```"


CHART = fence(
    "proxima-chart",
    '{"kind":"bar","title":"Risk by factor","unit":"%",'
    '"data":[{"label":"Logo","value":72},{"label":"Expression","value":24}]}',
)


class TestParsing(unittest.TestCase):
    def test_prose_with_no_blocks_is_one_text_segment(self):
        segments = visuals.parse("Just an answer.")
        self.assertEqual(segments, [("text", "Just an answer.")])

    def test_text_and_blocks_keep_their_order(self):
        reply = f"Before.\n\n{CHART}\n\nAfter."
        kinds = [kind for kind, _ in visuals.parse(reply)]
        self.assertEqual(kinds, ["text", "chart", "text"])

    def test_a_mermaid_block_becomes_a_diagram(self):
        reply = fence("mermaid", "flowchart TD\n  A --> B")
        kind, code = visuals.parse(reply)[0]
        self.assertEqual(kind, "diagram")
        self.assertIn("flowchart TD", code)

    def test_a_table_block_becomes_a_table(self):
        reply = fence(
            "proxima-table",
            '{"columns":["Factor","Risk"],"rows":[["Logo","High"]]}',
        )
        kind, spec = visuals.parse(reply)[0]
        self.assertEqual(kind, "table")
        self.assertEqual(spec["columns"], ["Factor", "Risk"])
        self.assertEqual(spec["rows"], [["Logo", "High"]])

    def test_empty_reply_parses_to_nothing(self):
        self.assertEqual(visuals.parse(""), [])

    def test_has_visuals_distinguishes_prose_from_drawings(self):
        self.assertFalse(visuals.has_visuals("no blocks here"))
        self.assertTrue(visuals.has_visuals(CHART))


class TestDegradation(unittest.TestCase):
    """A block that cannot be drawn must still be seen."""

    def assert_degrades(self, body, tag="proxima-chart"):
        kind, payload = visuals.parse(fence(tag, body))[0]
        self.assertEqual(kind, "code", f"expected degradation, got {kind}")
        self.assertIn(body.strip()[:12], payload["body"])
        self.assertTrue(payload["reason"])
        return payload

    def test_unparseable_json_degrades_to_visible_text(self):
        self.assert_degrades('{"kind": "bar", "data": [')

    def test_a_chart_with_no_rows_degrades(self):
        self.assert_degrades('{"kind":"bar","data":[]}')

    def test_rows_without_numbers_degrade(self):
        self.assert_degrades('{"data":[{"label":"A","value":"lots"}]}')

    def test_a_table_with_no_columns_degrades(self):
        self.assert_degrades('{"rows":[["a"]]}', tag="proxima-table")

    def test_a_json_array_where_an_object_belongs_degrades(self):
        self.assert_degrades('[1, 2, 3]')

    def test_trailing_commas_are_repaired_rather_than_degraded(self):
        # Small models do this constantly; it is not worth losing a chart over.
        kind, spec = visuals.parse(
            fence("proxima-chart", '{"kind":"bar","data":[{"label":"A","value":1},],}')
        )[0]
        self.assertEqual(kind, "chart")
        self.assertEqual(spec["rows"], [{"label": "A", "value": 1.0}])

    def test_an_unclosed_fence_still_yields_what_it_can(self):
        reply = 'Here:\n```proxima-chart\n{"data":[{"label":"A","value":5}]}'
        kinds = [kind for kind, _ in visuals.parse(reply)]
        self.assertEqual(kinds, ["text", "chart"])


class TestNumbers(unittest.TestCase):
    def test_numbers_are_read_out_of_human_formatting(self):
        self.assertEqual(visuals.to_number("72%"), 72.0)
        self.assertEqual(visuals.to_number("$1,200"), 1200.0)
        self.assertEqual(visuals.to_number("-3.5"), -3.5)
        self.assertEqual(visuals.to_number(12), 12.0)

    def test_non_numbers_are_none_rather_than_zero(self):
        # Zero would be a silent lie on a chart; None drops the row.
        self.assertIsNone(visuals.to_number("many"))
        self.assertIsNone(visuals.to_number(None))
        self.assertIsNone(visuals.to_number(True))

    def test_percent_strings_survive_into_a_chart(self):
        _, spec = visuals.parse(
            fence("proxima-chart", '{"data":[{"label":"Logo","value":"78%"}]}')
        )[0]
        self.assertEqual(spec["rows"][0]["value"], 78.0)


class TestShapes(unittest.TestCase):
    """The model reaches for several shapes; accept the common ones."""

    def test_parallel_label_and_value_lists_are_accepted(self):
        _, spec = visuals.parse(
            fence("proxima-chart", '{"labels":["A","B"],"values":[1,2]}')
        )[0]
        self.assertEqual([r["label"] for r in spec["rows"]], ["A", "B"])

    def test_an_object_of_label_to_value_is_accepted(self):
        _, spec = visuals.parse(fence("proxima-chart", '{"data":{"A":1,"B":2}}'))[0]
        self.assertEqual([r["value"] for r in spec["rows"]], [1.0, 2.0])

    def test_a_list_of_objects_is_accepted_as_a_table(self):
        _, spec = visuals.parse(
            fence("proxima-table", '{"rows":[{"Factor":"Logo","Risk":"High"}]}')
        )[0]
        self.assertEqual(spec["columns"], ["Factor", "Risk"])
        self.assertEqual(spec["rows"], [["Logo", "High"]])

    def test_ragged_table_rows_are_padded_not_dropped(self):
        _, spec = visuals.parse(
            fence("proxima-table", '{"columns":["A","B","C"],"rows":[["x"]]}')
        )[0]
        self.assertEqual(spec["rows"], [["x", "", ""]])

    def test_row_and_column_counts_are_capped(self):
        rows = ",".join(f'{{"label":"L{i}","value":{i}}}' for i in range(60))
        _, spec = visuals.parse(fence("proxima-chart", f'{{"data":[{rows}]}}'))[0]
        self.assertEqual(len(spec["rows"]), visuals.MAX_ROWS)

    def test_an_unknown_kind_falls_back_to_a_bar(self):
        _, spec = visuals.parse(
            fence("proxima-chart", '{"kind":"sunburst","data":[{"label":"A","value":1}]}')
        )[0]
        self.assertEqual(spec["kind"], "bar")


class TestStreaming(unittest.TestCase):
    def test_a_half_written_block_is_held_back_from_the_stream(self):
        partial = 'Working on it.\n\n```proxima-chart\n{"kind":"bar","data":[{"lab'
        self.assertEqual(visuals.strip_blocks(partial), "Working on it.")

    def test_completed_blocks_are_stripped_leaving_the_prose(self):
        self.assertEqual(visuals.strip_blocks(f"Before.\n\n{CHART}\n\nAfter."),
                         "Before.\n\nAfter.")

    def test_stripping_prose_changes_nothing(self):
        self.assertEqual(visuals.strip_blocks("Plain answer."), "Plain answer.")


class TestChartBuilding(unittest.TestCase):
    def test_a_single_series_chart_builds(self):
        _, spec = visuals.parse(CHART)[0]
        chart = visuals.to_altair(spec)
        self.assertIn("layer", chart.to_dict())

    def test_a_grouped_chart_uses_the_fixed_palette_in_order(self):
        _, spec = visuals.parse(
            fence(
                "proxima-chart",
                '{"data":[{"label":"A","value":1,"series":"Us"},'
                '{"label":"A","value":2,"series":"Them"}]}',
            )
        )[0]
        self.assertEqual(spec["series"], ["Them", "Us"])
        built = visuals.to_altair(spec).to_dict()
        colours = built["encoding"]["color"]["scale"]["range"]
        self.assertEqual(colours, visuals.CATEGORICAL[:2])

    def test_every_kind_builds_without_raising(self):
        for kind in visuals.KINDS:
            _, spec = visuals.parse(
                fence("proxima-chart", f'{{"kind":"{kind}","data":[{{"label":"A","value":1}}]}}')
            )[0]
            visuals.to_altair(spec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
