"""Tests for ``jarvis show`` clap detection and HUD wiring."""

from __future__ import annotations

from click.testing import CliRunner

from openjarvis.cli import show_cmd
from openjarvis.cli.show_cmd import ClapDetector, WakeDetector

CHUNK = 0.064  # seconds per 1024-sample chunk at 16 kHz


def _run(detector: ClapDetector, amplitudes: list[float]) -> list[str | None]:
    return [detector.feed(a, i * CHUNK) for i, a in enumerate(amplitudes)]


def test_two_short_claps_are_detected() -> None:
    det = ClapDetector(threshold=1000, window=1.0)
    events = _run(det, [0, 5000, 0, 0, 0, 5000, 0])
    assert events.count("clap") == 2
    assert det.count == 2


def test_sustained_noise_counts_as_a_single_clap() -> None:
    # ~640 ms of continuous loud sound used to register as two claps once the
    # cooldown elapsed mid-sound.
    det = ClapDetector(threshold=1000, window=1.0)
    events = _run(det, [0] + [5000] * 10 + [0])
    assert events.count("clap") == 1
    assert det.count == 1


def test_echo_within_cooldown_is_ignored() -> None:
    det = ClapDetector(threshold=1000, window=1.0, cooldown=0.15)
    # Drop below threshold for one chunk, then spike again 128 ms after the
    # first clap: still the same clap's reverb.
    events = _run(det, [5000, 0, 5000, 0])
    assert events.count("clap") == 1


def test_window_expiry_resets_the_count() -> None:
    det = ClapDetector(threshold=1000, window=0.5)
    events = _run(det, [5000] + [0] * 10 + [5000])
    assert "expired" in events
    assert det.count == 1


def test_hud_url_prefers_running_vite_dev_server(monkeypatch) -> None:
    monkeypatch.setattr(
        show_cmd, "_check_server_running", lambda port, host="": port == 5173
    )
    assert show_cmd._hud_url(8000, 5173, "/jarvis") == "http://localhost:5173/jarvis"


def test_hud_url_falls_back_to_jarvis_serve(monkeypatch) -> None:
    monkeypatch.setattr(show_cmd, "_check_server_running", lambda port, host="": False)
    assert show_cmd._hud_url(8000, 5173, "/jarvis") == "http://localhost:8000/jarvis"


def test_env_vars_configure_threshold_mic_and_wake(monkeypatch) -> None:
    seen: dict = {}

    def fake_listen(mode, threshold, mic_device, clap_window):  # noqa: ANN001
        seen.update(mode=mode, threshold=threshold, mic=mic_device)
        raise KeyboardInterrupt

    monkeypatch.setattr(show_cmd, "_listen_for_wake", fake_listen)
    monkeypatch.setattr(show_cmd, "_hud_events", lambda port: _NullEvents())
    result = CliRunner().invoke(
        show_cmd.show,
        ["--no-web"],
        env={"JARVIS_CLAP_THRESH": "800", "JARVIS_MIC": "3", "JARVIS_WAKE": "both"},
    )
    assert result.exit_code == 0, result.output
    assert seen == {"mode": "both", "threshold": 800, "mic": 3}


def test_unknown_wake_mode_is_a_usage_error() -> None:
    result = CliRunner().invoke(show_cmd.show, ["--no-web", "--wake", "whistle"])
    assert result.exit_code == 2


# --- wake word -------------------------------------------------------------


class _FakeSegmenter:
    """Emits one segment on the chunk marked b"END"."""

    def feed(self, chunk, amplitude):  # noqa: ANN001
        return [b"\x00\x00" * 160] if chunk == b"END" else None


def _wake(mode, text="Jarvis"):  # noqa: ANN001
    return WakeDetector(
        mode,
        clap=ClapDetector(threshold=1000, window=1.0),
        segmenter=_FakeSegmenter(),
        transcribe=lambda wav: text,
    )


def test_wake_word_triggers_in_word_mode() -> None:
    assert _wake("word").feed(b"END", 0, 0.0) == ("wake_word", "Jarvis")


def test_other_speech_is_reported_but_does_not_trigger() -> None:
    det = _wake("word", text="o jarvis do filme é muito legal mesmo")
    assert det.feed(b"END", 0, 0.0) == (
        "heard",
        "o jarvis do filme é muito legal mesmo",
    )


def test_clap_mode_ignores_speech_and_word_mode_ignores_claps() -> None:
    clap_only = _wake("clap")
    assert clap_only.feed(b"END", 0, 0.0) is None
    word_only = _wake("word")
    assert word_only.feed(b"x", 5000, 0.0) is None


def test_both_mode_accepts_double_clap_and_wake_word() -> None:
    det = _wake("both")
    assert det.feed(b"x", 5000, 0.0) == ("clap", 1)
    assert det.feed(b"x", 0, 0.1) is None
    assert det.feed(b"x", 5000, 0.4) == ("double_clap", None)
    assert det.feed(b"END", 0, 2.0) == ("wake_word", "Jarvis")


def test_transcription_errors_do_not_crash_the_listener() -> None:
    def boom(_wav):  # noqa: ANN001
        raise RuntimeError("cuda")

    det = WakeDetector("word", segmenter=_FakeSegmenter(), transcribe=boom)
    assert det.feed(b"END", 0, 0.0) is None


def test_invalid_threshold_env_is_a_usage_error_not_an_import_crash() -> None:
    result = CliRunner().invoke(
        show_cmd.show, ["--no-web"], env={"JARVIS_CLAP_THRESH": "abc"}
    )
    assert result.exit_code == 2


class _NullEvents:
    def state(self, *_args, **_kwargs) -> None:
        pass

    def close(self) -> None:
        pass
