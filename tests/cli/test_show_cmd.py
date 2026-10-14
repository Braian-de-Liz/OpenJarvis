"""Tests for ``jarvis show`` clap detection and HUD wiring."""

from __future__ import annotations

from click.testing import CliRunner

from openjarvis.cli import show_cmd
from openjarvis.cli.show_cmd import ClapDetector

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


def test_env_vars_configure_threshold_and_mic(monkeypatch) -> None:
    seen: dict = {}

    def fake_listen(threshold, mic_device, clap_window):  # noqa: ANN001
        seen.update(threshold=threshold, mic=mic_device)
        raise KeyboardInterrupt

    monkeypatch.setattr(show_cmd, "_listen_for_double_clap", fake_listen)
    monkeypatch.setattr(show_cmd, "_hud_events", lambda port: _NullEvents())
    result = CliRunner().invoke(
        show_cmd.show,
        ["--no-web"],
        env={"JARVIS_CLAP_THRESH": "800", "JARVIS_MIC": "3"},
    )
    assert result.exit_code == 0, result.output
    assert seen == {"threshold": 800, "mic": 3}


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
