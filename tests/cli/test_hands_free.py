"""Tests for the hands-free voice session helpers and turn loop."""

from __future__ import annotations

import io
import struct
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.cli import _hands_free as hf


@pytest.mark.parametrize(
    "text",
    [
        "Jarvis, desligar.",
        "jarvis desliga",
        "Pode parar",
        "Pare!",
        "Volta a ouvir as palmas",
        "Jarvis, volte a ouvir palmas",
        "Encerrar",
        "tchau jarvis",
        "Ok Jarvis, pode dormir",
        "Até logo",
    ],
)
def test_exit_phrases(text):
    assert hf.is_exit_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "para o Spotify",
        "abre o navegador e depois para",
        "desliga o monitor",
        "Qual a previsão do tempo?",
        "parar a música",
    ],
)
def test_commands_are_not_exit_phrases(text):
    assert not hf.is_exit_phrase(text)


def test_noise_transcripts():
    assert hf.is_noise_transcript("")
    assert hf.is_noise_transcript("Legendas pela comunidade Amara.org")
    assert hf.is_noise_transcript("Obrigado por assistir!")
    assert not hf.is_noise_transcript("aumente o volume")


@pytest.mark.parametrize(
    "text,ok",
    [
        ("Sim, pode", True),
        ("Não", False),
        ("pode sim", True),
        ("não, cancela", False),
        ("hmm", False),
    ],
)
def test_affirmative(text, ok):
    assert hf.is_affirmative(text) is ok


def test_speakable_strips_markdown():
    md = "**Pronto!** Volume em `50%`.\n- item um\n```python\nprint(1)\n```\n[link](http://x.y)"
    out = hf._speakable(md)
    assert (
        "*" not in out and "`" not in out and "print" not in out and "http" not in out
    )
    assert "Pronto!" in out and "link" in out


def test_threshold_from_ambient_has_floor():
    assert hf.threshold_from_ambient(0) == hf._MIN_THRESHOLD
    assert hf.threshold_from_ambient(40) == pytest.approx(100)


def _wav(samples, sr=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def test_wav_envelope_normalized():
    loud = [8000, -8000] * 4000
    quiet = [100, -100] * 4000
    env, step = hf.wav_envelope(_wav(quiet + loud))
    assert env and max(env) == pytest.approx(1.0)
    assert env[0] < 0.1


# -- fake microphone ---------------------------------------------------------


class _FakeStream:
    def __init__(self, levels):
        self._levels = list(levels)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        amp = self._levels.pop(0) if self._levels else 0
        return struct.pack(f"<{n}h", *([amp] * n)), False


@pytest.fixture
def fake_mic(monkeypatch):
    import sys

    holder = SimpleNamespace(levels=[])
    fake_sd = SimpleNamespace(RawInputStream=lambda **kw: _FakeStream(holder.levels))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    return holder


def test_record_utterance_returns_none_when_silent(fake_mic):
    fake_mic.levels = [0] * 100
    assert hf.record_utterance(threshold=50, wait_seconds=1.0) is None


def test_record_utterance_captures_speech_with_preroll(fake_mic):
    fake_mic.levels = [0] * 3 + [500] * 10 + [0] * 40
    levels = []
    audio = hf.record_utterance(
        threshold=50, wait_seconds=5, silence_seconds=0.5, on_level=levels.append
    )
    assert audio is not None
    with wave.open(io.BytesIO(audio)) as wf:
        frames = wf.getnframes() // hf._CHUNK
    # preroll (≤5) + 6 remaining voiced + ~8 silence chunks
    assert 12 <= frames <= 25
    assert levels and max(levels) == 1.0


# -- session loop ------------------------------------------------------------


class _Events:
    enabled = False

    def __init__(self):
        self.log = []

    def emit(self, t, **d):
        self.log.append((t, d))

    def state(self, s, reason=""):
        self.log.append(("state", {"state": s, "reason": reason}))


def _session(monkeypatch, transcripts, idle=5.0):
    stt = MagicMock()
    stt.transcribe.side_effect = [SimpleNamespace(text=t) for t in transcripts]
    voice = MagicMock()
    voice.get_stt_backend.return_value = stt
    recordings = iter([b"wav"] * len(transcripts))
    monkeypatch.setattr(hf, "record_utterance", lambda **kw: next(recordings, None))
    spoken = []
    monkeypatch.setattr(
        "openjarvis.cli._voice_chat.speak", lambda text, *a, **k: spoken.append(text)
    )
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)
    events = _Events()
    s = hf.HandsFreeSession(
        MagicMock(),
        voice,
        events=events,
        idle_timeout=idle,
        silence_threshold=40,
        language="pt",
    )
    return s, events, spoken, stt


def test_listen_skips_noise_and_returns_command(monkeypatch):
    s, events, _, stt = _session(
        monkeypatch, ["Obrigado por assistir", "aumente o volume"]
    )
    assert s.listen() == "aumente o volume"
    assert stt.transcribe.call_args.kwargs["language"] == "pt"
    assert ("transcript", {"text": "aumente o volume"}) in events.log
    states = [d["state"] for t, d in events.log if t == "state"]
    assert states[:2] == ["listening", "transcribing"]


def test_exit_phrase_ends_session(monkeypatch):
    s, events, spoken, _ = _session(monkeypatch, ["Jarvis, desligar"])
    assert s.listen() is None
    assert s.end_reason == "exit_phrase"
    assert spoken  # spoken goodbye
    assert ("state", {"state": "ended", "reason": "exit_phrase"}) in events.log


def test_idle_timeout_ends_session(monkeypatch):
    s, events, _, _ = _session(monkeypatch, [], idle=0.05)
    assert s.listen() is None
    assert s.end_reason == "idle_timeout"


def test_say_emits_response_and_speaking(monkeypatch):
    s, events, spoken, _ = _session(monkeypatch, [])
    s.say("**Feito.**")
    assert spoken == ["Feito."]
    assert ("response", {"text": "**Feito.**"}) in events.log
    assert ("state", {"state": "speaking", "reason": ""}) in events.log


def test_voice_confirm(monkeypatch):
    s, _, _, _ = _session(monkeypatch, ["sim, pode"])
    assert s.confirm("fechar o Chrome") is True
    s, _, _, _ = _session(monkeypatch, ["não"])
    assert s.confirm("desligar o PC") is False


def test_publisher_disabled_without_url():
    pub = hf.VoiceEventPublisher(None)
    assert not pub.enabled
    pub.emit("state", state="idle")  # no-op, must not raise
    pub.close()


def test_publisher_posts_to_relay(monkeypatch):
    sent = []

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers):
            sent.append((url, json, headers))

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)
    pub = hf.VoiceEventPublisher("http://127.0.0.1:8000/", api_key="k")
    pub.state("listening")
    pub.close()
    assert sent == [
        (
            "http://127.0.0.1:8000/v1/voice/events",
            {"type": "state", "data": {"state": "listening"}},
            {"Authorization": "Bearer k"},
        )
    ]


# ---------------------------------------------------------------------------
# Wake word
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Jarvis", "Jarvis.", "Ei, Jarvis!", "ok jarvis", "Jarvas?", "Djarvis acorda"],
)
def test_wake_phrase_accepts_short_calls(text):
    assert hf.is_wake_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "obrigado por assistir",
        "o jarvis do filme é muito legal mesmo",  # a sentence about him
        "Travis",
    ],
)
def test_wake_phrase_rejects_other_speech(text):
    assert not hf.is_wake_phrase(text)


def _feed(seg, pattern):
    """Feed loud ('L') / quiet ('q') chunks; return emitted segments."""
    out = []
    for i, c in enumerate(pattern):
        chunk = bytes([i % 256, 0])
        got = seg.feed(chunk, 1000.0 if c == "L" else 0.0)
        if got is not None:
            out.append(got)
    return out


def test_segmenter_emits_short_utterance_with_preroll():
    seg = hf.SpeechSegmenter(100, min_voiced=3, silence=2, max_chunks=20, preroll=4)
    segments = _feed(seg, "qq" + "LLLL" + "qq")
    assert len(segments) == 1
    # pre-roll holds the last 4 chunks (1 quiet + 3 voiced) + 1 voiced + 2 quiet
    assert len(segments[0]) == 7


def test_segmenter_ignores_blips_and_drops_long_talk():
    seg = hf.SpeechSegmenter(100, min_voiced=3, silence=2, max_chunks=5, preroll=2)
    assert _feed(seg, "LqLq" * 3) == []  # never 3 loud chunks in a row
    assert _feed(seg, "L" * 12 + "qq") == []  # longer than max_chunks
    assert len(_feed(seg, "LLL" + "qq")) == 1  # and it recovers afterwards
