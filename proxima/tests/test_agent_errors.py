# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Tests for how the agent explains a failed generation.

Run with:  python -m pytest tests -q      (or plain `python tests/test_agent_errors.py`)

These exist because the four ways a local model can fail need four different
answers, and for a long time they all got one: "start Ollama". A 500 from a
running server sent people to restart the only part that worked, so what each
case tells the user is the thing worth pinning down.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxima"))

import requests  # noqa: E402

from agent import ProximaAgent  # noqa: E402
from database import DatabaseManager  # noqa: E402

# The real thing, from a Mac whose Metal shader compiler had gone stale: Ollama
# answered, then reported that the process behind it had died on startup.
METAL_CRASH = (
    "llama-server process has terminated: error: Error Domain=MTLLibraryErrorDomain "
    'Code=3 "Compiler encountered XPC_ERROR_CONNECTION_INVALID (is the OS shutting '
    'down?)"\nerror: failed to create library'
)


class FakeResponse:
    """Just enough of `requests.Response` for the error paths."""

    def __init__(self, status_code: int, body: str = "", lines: list[str] | None = None):
        self.status_code = status_code
        self.text = body
        self._lines = lines or []

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Server Error", response=self
            )

    def iter_lines(self):
        for line in self._lines:
            yield line.encode("utf-8")


def agent() -> ProximaAgent:
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    return ProximaAgent(database=DatabaseManager(path))


class TestFailureExplanations(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = agent()

    def test_refused_connection_says_the_server_is_down(self) -> None:
        message = self.agent._explain_failure(requests.exceptions.ConnectionError("refused"))

        self.assertIn("isn't running", message)
        self.assertIn("ollama serve", message)
        # Nothing was reached, so the model is not the thing to go fix.
        self.assertNotIn("ollama pull", message)

    def test_missing_model_says_to_pull_it(self) -> None:
        response = FakeResponse(404, json.dumps({"error": "model 'llama3.2' not found"}))
        exc = requests.exceptions.HTTPError(response=response)

        message = self.agent._explain_failure(exc)

        self.assertIn("ollama pull llama3.2", message)
        self.assertIn("is running", message)
        self.assertNotIn("isn't running", message)

    def test_server_error_surfaces_what_ollama_reported(self) -> None:
        response = FakeResponse(500, json.dumps({"error": METAL_CRASH}))
        exc = requests.exceptions.HTTPError(response=response)

        message = self.agent._explain_failure(exc)

        # The regression this file exists for: a 500 must not be reported as a
        # server that needs starting, and must show the cause it came with.
        self.assertNotIn("isn't running", message)
        self.assertNotIn("ollama pull", message)
        self.assertIn("MTLLibraryErrorDomain", message)
        self.assertIn("failed to load", message)
        self.assertIn("pkill", message)

    def test_timeout_is_not_reported_as_a_dead_server(self) -> None:
        message = self.agent._explain_failure(requests.exceptions.ReadTimeout("slow"))

        self.assertIn("in time", message)
        self.assertNotIn("isn't running", message)

    def test_other_client_errors_keep_their_status(self) -> None:
        response = FakeResponse(400, json.dumps({"error": "invalid options"}))
        exc = requests.exceptions.HTTPError(response=response)

        message = self.agent._explain_failure(exc)

        self.assertIn("400", message)
        self.assertIn("invalid options", message)

    def test_unreadable_reply_is_its_own_case(self) -> None:
        exc = json.JSONDecodeError("Expecting value", "<html>", 0)

        message = self.agent._explain_failure(exc)

        self.assertIn("couldn't read", message)


class TestReportedError(unittest.TestCase):
    """Reading Ollama's explanation must never fail louder than the failure."""

    def test_reads_the_error_field(self) -> None:
        response = FakeResponse(500, json.dumps({"error": "boom"}))
        self.assertEqual(ProximaAgent._reported_error(response), "boom")

    def test_falls_back_to_the_raw_body(self) -> None:
        response = FakeResponse(500, "plain text failure")
        self.assertEqual(ProximaAgent._reported_error(response), "plain text failure")

    def test_survives_a_body_that_cannot_be_read(self) -> None:
        class Dead:
            status_code = 500

            @property
            def text(self):
                raise requests.exceptions.ChunkedEncodingError("connection gone")

        self.assertEqual(ProximaAgent._reported_error(Dead()), "")

    def test_survives_no_response_at_all(self) -> None:
        self.assertEqual(ProximaAgent._reported_error(None), "")

    def test_caps_a_runaway_body(self) -> None:
        response = FakeResponse(500, json.dumps({"error": "x" * 5000}))
        self.assertEqual(len(ProximaAgent._reported_error(response)), 800)


class TestStreamResponse(unittest.TestCase):
    """End to end through `stream_response`, where the user actually sees this."""

    def setUp(self) -> None:
        self.agent = agent()
        self._real_post = requests.post

    def tearDown(self) -> None:
        requests.post = self._real_post

    def test_a_500_reaches_the_user_as_a_backend_failure(self) -> None:
        requests.post = lambda *a, **k: FakeResponse(500, json.dumps({"error": METAL_CRASH}))

        out = "".join(self.agent.stream_response("hello"))

        self.assertIn("MTLLibraryErrorDomain", out)
        self.assertNotIn("isn't running", out)

    def test_an_error_inside_the_stream_is_a_backend_failure(self) -> None:
        # Ollama answers 200, streams, then reports the model died partway.
        lines = [
            json.dumps({"response": "Dark mode "}),
            json.dumps({"error": METAL_CRASH}),
        ]
        requests.post = lambda *a, **k: FakeResponse(200, lines=lines)

        out = "".join(self.agent.stream_response("hello"))

        self.assertIn("Dark mode ", out)
        self.assertIn("MTLLibraryErrorDomain", out)
        self.assertIn("failed to load", out)

    def test_a_refused_connection_reaches_the_user_as_a_dead_server(self) -> None:
        def refuse(*args, **kwargs):
            raise requests.exceptions.ConnectionError("refused")

        requests.post = refuse

        out = "".join(self.agent.stream_response("hello"))

        self.assertIn("isn't running", out)
        self.assertIn("ollama serve", out)

    def test_a_good_stream_is_untouched(self) -> None:
        lines = [
            json.dumps({"response": "Dark "}),
            json.dumps({"response": "mode."}),
            json.dumps({"done": True}),
        ]
        requests.post = lambda *a, **k: FakeResponse(200, lines=lines)

        self.assertEqual("".join(self.agent.stream_response("hello")), "Dark mode.")


if __name__ == "__main__":
    unittest.main()
