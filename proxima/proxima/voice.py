# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Speech-to-text for the chat composer.

Lets someone talk to Proxima instead of typing. Recording is handled by
Streamlit's own ``st.audio_input`` widget; this module only turns the resulting
clip into text.

Transcription runs locally through faster-whisper, which keeps the audio on this
machine — the same principle as pointing the agent at a local Ollama rather than
a hosted API. The dependency is optional and imported lazily: without it the UI
still shows the recorder and explains how to switch transcription on, rather
than crashing at import time.

    pip install faster-whisper
"""

from __future__ import annotations

import os
import tempfile

import streamlit as st

# "base.en" is the sweet spot for dictating a sentence or two of product
# feedback: ~140MB, a few seconds on CPU, and accurate enough for English
# speech that the user is about to read back and edit anyway.
MODEL_SIZE = "base.en"

INSTALL_HINT = "pip install faster-whisper"


def backend_available() -> bool:
    """Is the transcriber installed? Drives the fallback copy in the UI."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@st.cache_resource(show_spinner=False)
def _model():
    """Load the model once per server process.

    The first call downloads the weights (~140MB) into the local HuggingFace
    cache, so it is slow exactly once. int8 on CPU is the cheapest setting that
    still transcribes reliably.
    """
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def transcribe(audio: bytes) -> str:
    """Turn a recorded clip into text. Returns "" when nothing was said.

    faster-whisper decodes via ffmpeg, which wants a real file, so the clip goes
    through a temp file that is always cleaned up.
    """
    if not audio:
        return ""

    handle, path = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    try:
        with open(path, "wb") as clip:
            clip.write(audio)

        segments, _info = _model().transcribe(path, beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()
    finally:
        os.unlink(path)
