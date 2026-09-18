# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Tests for the accessibility settings.

The rule these enforce: a setting must change something. It is easy to ship a
panel of switches that only write to a dict, and that is worse than shipping
nothing — it tells someone their need has been handled when it has not. So each
test here asserts on the artefact the setting produces: the stylesheet, the
chart palette, or the prompt.

The contrast check computes WCAG ratios rather than trusting the constants. A
palette called "high contrast" that is not is the exact failure this feature
exists to prevent.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

import accessibility as a11y  # noqa: E402
import theme  # noqa: E402
import visuals  # noqa: E402
import workspace  # noqa: E402


def luminance(colour: str) -> float:
    raw = colour.lstrip("#")
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(one: str, two: str) -> float:
    high, low = sorted([luminance(one), luminance(two)], reverse=True)
    return (high + 0.05) / (low + 0.05)


class TestNormalising(unittest.TestCase):
    def test_nothing_stored_gives_the_current_behaviour(self):
        self.assertEqual(a11y.normalise(None), a11y.DEFAULTS)
        self.assertEqual(a11y.normalise({}), a11y.DEFAULTS)

    def test_an_unknown_choice_falls_back_rather_than_sticking(self):
        settings = a11y.normalise({"text_scale": "enormous", "contrast": "high"})
        self.assertEqual(settings["text_scale"], "normal")
        self.assertEqual(settings["contrast"], "high")

    def test_unknown_keys_are_dropped(self):
        self.assertNotIn("tracking", a11y.normalise({"tracking": True}))

    def test_every_choice_has_a_label(self):
        for key, options in a11y.CHOICES.items():
            for option in options:
                self.assertIn(option, a11y.LABELS[key], f"{key}/{option}")


class TestContrast(unittest.TestCase):
    """High contrast has to actually be high contrast."""

    def test_high_contrast_clears_wcag_aa_for_body_text(self):
        palette = a11y.HIGH_CONTRAST
        for ink in ("text", "dim", "faint", "accent"):
            for ground in ("bg", "surface", "surface_hi"):
                ratio = contrast(palette[ink], palette[ground])
                self.assertGreaterEqual(
                    ratio, 4.5, f"{ink} on {ground} is only {ratio:.2f}:1"
                )

    def test_high_contrast_is_an_improvement_on_the_default_theme(self):
        # The default theme's faintest ink sits at ~3.7:1 — legible as a label,
        # under AA for body text. This mode is the answer to that.
        for ink in ("text", "dim", "faint"):
            self.assertGreater(
                contrast(a11y.HIGH_CONTRAST[ink], a11y.HIGH_CONTRAST["bg"]),
                contrast(theme.TOKENS[ink], theme.TOKENS["bg"]),
                ink,
            )


class TestStylesheet(unittest.TestCase):
    def test_defaults_emit_no_css_at_all(self):
        # Nothing chosen, nothing overridden — the theme stands as written.
        self.assertEqual(a11y.css(a11y.DEFAULTS), "")

    def test_text_scale_moves_the_root_font_size(self):
        self.assertIn("font-size: 21px", a11y.css({"text_scale": "larger"}))
        self.assertIn("font-size: 14px", a11y.css({"text_scale": "small"}))
        self.assertNotIn("font-size", a11y.css({"text_scale": "normal"}))

    def test_high_contrast_redefines_the_theme_tokens(self):
        css = a11y.css({"contrast": "high"})
        self.assertIn("--px-text: #FFFFFF", css)
        self.assertIn("--px-bg: #000000", css)

    def test_reduced_motion_disables_animation_and_transitions(self):
        css = a11y.css({"motion": "reduced"})
        self.assertIn("animation-duration", css)
        self.assertIn("transition-duration", css)

    def test_larger_targets_reach_the_wcag_size(self):
        self.assertIn("min-height: 44px", a11y.css({"big_targets": True}))

    def test_focus_ring_draws_an_outline(self):
        self.assertIn(":focus-visible", a11y.css({"focus_ring": True}))

    def test_reading_font_loads_and_applies_one(self):
        css = a11y.css({"reading_font": True})
        self.assertIn("Lexend", css)
        self.assertIn("--px-font-body", css)

    def test_each_switch_changes_the_stylesheet(self):
        # The point of the module: no setting is decorative.
        for key, value in (
            ("text_scale", "large"), ("contrast", "high"), ("motion", "reduced"),
            ("big_targets", True), ("focus_ring", True), ("reading_font", True),
        ):
            self.assertNotEqual(a11y.css({key: value}), "", key)


class TestChartColour(unittest.TestCase):
    def test_the_default_palette_is_the_measured_one(self):
        self.assertEqual(a11y.palette({}), visuals.CATEGORICAL)

    def test_maximum_separation_keeps_only_the_all_pairs_safe_slots(self):
        # Three is not a round number: it is how many of these hues stay apart
        # under protanopia when any two marks can sit side by side.
        self.assertEqual(len(a11y.palette({"chart_colour": "separated"})), 3)
        self.assertEqual(a11y.series_cap({"chart_colour": "separated"}), 3)

    def test_one_hue_is_a_monotone_ramp(self):
        ramp = a11y.palette({"chart_colour": "one_hue"})
        lightness = [luminance(c) for c in ramp]
        self.assertEqual(lightness, sorted(lightness, reverse=True))

    def test_one_hue_forces_a_second_channel(self):
        # With one hue the colour carries nothing, so the labels are not
        # optional — they are the only thing telling the series apart.
        self.assertTrue(a11y.label_always({"chart_colour": "one_hue"}))

    def test_never_colour_alone_forces_labels_on_any_palette(self):
        self.assertTrue(a11y.label_always({"colour_alone": False}))
        self.assertFalse(a11y.label_always({}))

    def test_the_cap_folds_extra_series_into_other(self):
        spec = {
            "kind": "bar", "title": "", "unit": "", "note": "",
            "series": ["A", "B", "C", "D"],
            "rows": [{"label": "x", "value": 1, "series": s} for s in "ABCD"],
        }
        folded = visuals.fold_series(spec, 3)
        self.assertEqual(folded["series"], ["A", "B", "Other"])
        self.assertEqual({r["series"] for r in folded["rows"]}, {"A", "B", "Other"})

    def test_folding_leaves_a_short_series_list_alone(self):
        spec = {"series": ["A", "B"], "rows": [{"label": "x", "value": 1, "series": "A"}]}
        self.assertIs(visuals.fold_series(spec, 3), spec)

    def test_the_chosen_palette_reaches_the_built_chart(self):
        _, spec = visuals.parse(
            '```proxima-chart\n{"data":[{"label":"x","value":1,"series":"A"},'
            '{"label":"x","value":2,"series":"B"}]}\n```'
        )[0]
        built = visuals.to_altair(spec, a11y.appearance({"chart_colour": "one_hue"})).to_dict()
        # One hue forces direct labels, which makes this a layered chart.
        encoding = built.get("encoding") or built["layer"][0]["encoding"]
        self.assertEqual(encoding["color"]["scale"]["range"], a11y.ONE_HUE[:2])


class TestReplyLength(unittest.TestCase):
    def test_balanced_adds_nothing_to_the_prompt(self):
        self.assertEqual(a11y.reply_note({}), "")

    def test_brief_and_detailed_each_say_something_different(self):
        brief = a11y.reply_note({"reply_length": "brief"})
        detailed = a11y.reply_note({"reply_length": "detailed"})
        self.assertTrue(brief and detailed)
        self.assertNotEqual(brief, detailed)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._users = workspace.USERS
        workspace.USERS = Path(self._tmp.name)

    def tearDown(self):
        workspace.USERS = self._users
        self._tmp.cleanup()

    def test_settings_survive_a_restart(self):
        # An accessibility choice resetting on restart is its own failure.
        workspace.save_state({}, 0, 5, settings={"contrast": "high", "text_scale": "larger"})
        stored = workspace.load_state(5)["settings"]
        self.assertEqual(stored["contrast"], "high")
        self.assertEqual(stored["text_scale"], "larger")

    def test_a_chat_only_save_does_not_reset_them(self):
        workspace.save_state({}, 0, 5, settings={"contrast": "high"})
        workspace.save_sessions({}, 0, 5)
        self.assertEqual(workspace.load_state(5)["settings"]["contrast"], "high")

    def test_a_file_with_no_settings_loads_the_defaults(self):
        workspace.save_state({}, 0, 5)
        self.assertEqual(workspace.load_state(5)["settings"], a11y.DEFAULTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
