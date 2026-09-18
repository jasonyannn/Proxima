# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Tests for projects and scoped memory.

Two things are worth guarding here, and they are not the CRUD:

1. **Scope leakage.** "This project" must never quietly widen to "everything".
   The failure is silent — the agent simply starts answering with context from
   an unrelated product — so it needs a test rather than a look.
2. **Migration.** sessions.json files written before projects existed are on
   real machines. They have to load, with their chats intact and unfiled.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

import memory  # noqa: E402
import workspace  # noqa: E402


def chat(title="", project_id=None, messages=None, ordinal=1):
    return {
        "title": title,
        "project_id": project_id,
        "messages": messages if messages is not None else [],
        "created": datetime(2026, 1, 1, 12, 0, 0),
        "ordinal": ordinal,
    }


def exchange(user, agent="ok"):
    return {"user": user, "agent": agent}


class TestScope(unittest.TestCase):
    def test_unknown_values_fall_back_to_the_default(self):
        self.assertEqual(workspace.normalise_scope("nonsense"), workspace.DEFAULT_SCOPE)
        self.assertEqual(workspace.normalise_scope(None), workspace.DEFAULT_SCOPE)
        self.assertEqual(workspace.normalise_scope(""), workspace.DEFAULT_SCOPE)

    def test_the_old_boolean_toggle_still_means_something(self):
        # "Learn from my chats" was a checkbox before it was a scope.
        self.assertEqual(workspace.normalise_scope(True), "all")
        self.assertEqual(workspace.normalise_scope(False), "off")

    def test_known_scopes_survive_a_round_trip(self):
        for scope in workspace.SCOPES:
            self.assertEqual(workspace.normalise_scope(scope), scope)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._users = workspace.USERS
        workspace.USERS = Path(self._tmp.name)

    def tearDown(self):
        workspace.USERS = self._users
        self._tmp.cleanup()

    def test_projects_and_chats_round_trip(self):
        projects = {"p1": {"name": "Storefront", "brief": "A shop builder.", "ordinal": 1,
                           "created": datetime(2026, 1, 1)}}
        chats = {"c1": chat("Pricing", "p1"), "c2": chat("Unrelated")}

        workspace.save_state(chats, 2, 7, projects=projects, project_counter=1, scope="project")
        state = workspace.load_state(7)

        self.assertEqual(list(state["projects"]), ["p1"])
        self.assertEqual(state["projects"]["p1"]["brief"], "A shop builder.")
        self.assertEqual(state["chats"]["c1"]["project_id"], "p1")
        self.assertIsNone(state["chats"]["c2"]["project_id"])
        self.assertEqual(state["scope"], "project")
        self.assertEqual(state["counter"], 2)
        self.assertEqual(state["project_counter"], 1)

    def test_a_chat_pointing_at_a_deleted_project_is_unfiled(self):
        # Rather than vanishing: the sidebar renders chats by project, so a
        # dangling project_id would hide a conversation that still exists.
        workspace.save_state({"c1": chat("Orphan", "gone")}, 1, 7, projects={}, project_counter=0)
        state = workspace.load_state(7)
        self.assertIn("c1", state["chats"])
        self.assertIsNone(state["chats"]["c1"]["project_id"])

    def test_a_pre_projects_file_still_loads(self):
        legacy = {
            "counter": 2,
            "recall": True,
            "chats": {
                "c1": {"messages": [exchange("hello")], "created": "2026-01-01T12:00:00",
                       "title": "Old chat", "ordinal": 1},
            },
        }
        path = workspace.sessions_file(7)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(legacy))

        state = workspace.load_state(7)
        self.assertEqual(state["chats"]["c1"]["title"], "Old chat")
        self.assertIsNone(state["chats"]["c1"]["project_id"])
        self.assertEqual(state["projects"], {})
        # The old boolean carried a meaning; it is honoured, not dropped.
        self.assertEqual(state["scope"], "all")

    def test_a_chat_only_save_does_not_delete_the_projects(self):
        projects = {"p1": {"name": "Storefront", "brief": "b", "ordinal": 1,
                           "created": datetime(2026, 1, 1)}}
        workspace.save_state({"c1": chat("A", "p1")}, 1, 7, projects=projects,
                             project_counter=1, scope="project")

        # The path an older caller takes — it knows nothing about projects.
        workspace.save_sessions({"c1": chat("A", "p1")}, 1, 7)

        state = workspace.load_state(7)
        self.assertEqual(list(state["projects"]), ["p1"])
        self.assertEqual(state["scope"], "project")

    def test_a_corrupt_file_reads_as_empty_rather_than_raising(self):
        path = workspace.sessions_file(7)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        state = workspace.load_state(7)
        self.assertEqual(state["chats"], {})
        self.assertEqual(state["projects"], {})

    def test_chats_in_project_selects_by_project(self):
        chats = {"a": chat("A", "p1"), "b": chat("B", "p2"), "c": chat("C")}
        self.assertEqual(list(workspace.chats_in_project(chats, "p1")), ["a"])
        self.assertEqual(list(workspace.chats_in_project(chats, "p2")), ["b"])
        self.assertEqual(list(workspace.chats_in_project(chats, None)), ["c"])


class TestRecallScope(unittest.TestCase):
    """The leak tests. Each asserts what must *not* reach the prompt."""

    def setUp(self):
        self.projects = {
            "p1": {"name": "Storefront", "brief": "A no-code shop builder."},
            "p2": {"name": "Telemetry", "brief": "An analytics tool."},
        }
        self.chats = {
            "a": chat("Pricing", "p1", [exchange("how should we price the shop builder")]),
            "b": chat("Churn", "p2", [exchange("churn dashboards for telemetry")]),
            "c": chat("Loose", None, [exchange("something unfiled")]),
            "open": chat("Open", "p1", [exchange("what am i working on")]),
        }

    def digest(self, scope, project_id="p1", current="open"):
        return memory.recall_digest(
            self.chats, current, scope=scope, project_id=project_id,
            projects=self.projects,
        )

    def test_off_recalls_nothing(self):
        self.assertEqual(self.digest("off"), "")

    def test_project_scope_excludes_other_projects(self):
        text = self.digest("project")
        self.assertIn("price the shop builder", text)
        self.assertNotIn("telemetry", text.lower())
        self.assertNotIn("unfiled", text)

    def test_project_scope_on_an_unfiled_chat_recalls_nothing(self):
        # "This project" cannot honestly mean "all of them" when there is no
        # project. Widening here would hand the user a setting they refused.
        self.assertEqual(self.digest("project", project_id=None, current="c"), "")

    def test_all_scope_reaches_every_other_chat(self):
        text = self.digest("all")
        self.assertIn("price the shop builder", text)
        self.assertIn("churn dashboards", text)
        self.assertIn("something unfiled", text)

    def test_the_open_chat_is_never_in_its_own_digest(self):
        # It is already passed as conversation history; repeating it spends
        # context to say the same thing twice.
        for scope in ("project", "all"):
            self.assertNotIn("what am i working on", self.digest(scope))

    def test_all_scope_tags_each_line_with_its_project(self):
        text = self.digest("all")
        self.assertIn("[Storefront · Pricing]", text)
        self.assertIn("[Telemetry · Churn]", text)

    def test_the_digest_respects_its_line_limit(self):
        many = {
            f"c{i}": chat(f"Chat {i}", "p1", [exchange(f"message {i}")])
            for i in range(20)
        }
        many["open"] = chat("Open", "p1")
        text = memory.recall_digest(many, "open", scope="project", project_id="p1", limit=4)
        self.assertEqual(len(text.splitlines()), 4)

    def test_the_digest_respects_its_character_budget(self):
        many = {
            f"c{i}": chat(f"Chat {i}", "p1", [exchange("x" * 200)])
            for i in range(20)
        }
        many["open"] = chat("Open", "p1")
        text = memory.recall_digest(
            many, "open", scope="project", project_id="p1", limit=99, budget=400
        )
        self.assertLessEqual(len(text), 400 + 80)

    def test_an_unanswered_exchange_still_contributes_its_question(self):
        chats = {
            "a": chat("Half", "p1", [{"user": "a question", "agent": None}]),
            "open": chat("Open", "p1"),
        }
        text = memory.recall_digest(chats, "open", scope="project", project_id="p1",
                                    projects=self.projects)
        self.assertIn("a question", text)
        self.assertNotIn("You answered", text)


class TestPromptComposition(unittest.TestCase):
    def setUp(self):
        self.projects = {"p1": {"name": "Storefront", "brief": "A no-code shop builder."}}
        self.chats = {
            "a": chat("Pricing", "p1", [exchange("how should we price it")]),
            "open": chat("Open", "p1"),
        }
        self.project = {"id": "p1", **self.projects["p1"]}

    def compose(self, **kwargs):
        options = dict(
            language="English", scope="project", project=self.project,
            chats=self.chats, current_chat_id="open", projects=self.projects,
        )
        options.update(kwargs)
        return memory.compose_system_prompt("BASE", **options)

    def test_the_base_prompt_always_comes_first(self):
        self.assertTrue(self.compose().startswith("BASE"))

    def test_the_brief_is_included_for_a_projects_chat(self):
        self.assertIn("A no-code shop builder.", self.compose())

    def test_the_brief_sits_above_the_digest(self):
        # When the durable brief and the lossy digest disagree, the brief
        # should be the thing the model read most recently before the message.
        text = self.compose()
        self.assertLess(text.index("no-code shop builder"), text.index("how should we price it"))

    def test_a_chat_with_no_project_gets_no_brief(self):
        text = self.compose(project=None, scope="off")
        self.assertNotIn("no-code shop builder", text)

    def test_an_empty_brief_adds_no_block(self):
        text = self.compose(project={"id": "p1", "name": "Storefront", "brief": "   "})
        self.assertNotIn("standing brief", text)

    def test_language_instruction_only_appears_for_other_languages(self):
        self.assertNotIn("Always write your replies", self.compose())
        self.assertIn("Spanish", self.compose(language="Spanish"))

    def test_scope_off_leaves_the_transcripts_out_but_keeps_the_brief(self):
        text = self.compose(scope="off")
        self.assertIn("A no-code shop builder.", text)
        self.assertNotIn("how should we price it", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
