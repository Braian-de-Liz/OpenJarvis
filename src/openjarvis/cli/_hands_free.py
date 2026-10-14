"""Hands-free voice session: continuous listen → STT → LLM → TTS loop.

Used by ``jarvis chat --hands-free`` (and therefore ``jarvis show`` after the
double clap). Unlike ``--voice``, no key press is needed between turns:

* the mic opens automatically after each reply;
* the session ends after ``idle_timeout`` seconds without speech, or when the
  user says an exit phrase ("Jarvis, desligar", "pode parar", ...);
* every state change is POSTed to the local ``jarvis serve`` relay
  (``/v1/voice/events``) so the ``/jarvis`` HUD can mirror it live.

Event publishing is best-effort: if the server is down the session still
works, it just has no HUD.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
import unicodedata
from collections import deque
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHUNK = 1024  # ~64 ms per chunk at 16 kHz
_PREROLL_CHUNKS = 5  # ~320 ms kept before speech onset so syllables aren't cut
_MIN_SPEECH_CHUNKS = 4  # ~250 ms of voiced audio before we treat it as speech
_LEVEL_EVERY_CHUNKS = 2  # ~8 level events/s to the HUD

DEFAULT_IDLE_TIMEOUT = 30.0
DEFAULT_SILENCE_SECONDS = 1.2
DEFAULT_MAX_UTTERANCE = 30.0
_MIN_THRESHOLD = 12.0  # RMS floor; low-gain Windows mics speak at ~30-80 RMS
_AMBIENT_MULTIPLIER = 2.5

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", no_accents)).strip()


# Whole-utterance matches only, so "para o Spotify" never ends the session.
_EXIT_RE = re.compile(
    r"^(?:(?:ok|ei|hey|e ai)\s+)?(?:jarvis\s+)?"
    r"(?:"
    r"desliga(?:r)?|desligue(?: se)?|pode desligar|"
    r"para(?:r)?|pare|pode parar|"
    r"encerra(?:r)?|encerre|encerrar sessao|"
    r"(?:vai |pode )?dormir|"
    r"volta(?:r)? a ouvir(?: (?:as )?palmas)?|volte a ouvir(?: (?:as )?palmas)?|"
    r"tchau|ate logo|ate mais|"
    r"stop|goodbye|shut down|go to sleep"
    r")(?:\s+jarvis)?$"
)


def is_exit_phrase(text: str) -> bool:
    """True when the whole utterance is a session-ending command."""
    return bool(_EXIT_RE.match(_normalize(text)))


# Whisper invents these on near-silence / noise, especially in Portuguese.
_HALLUCINATIONS = {
    "legendas pela comunidade amara org",
    "legenda adriana zanotto",
    "obrigado por assistir",
    "obrigada por assistir",
    "inscreva se no canal",
    "thanks for watching",
    "thank you for watching",
    "you",
    "e ai",
    "",
}


def is_noise_transcript(text: str) -> bool:
    """True for empty or well-known Whisper hallucinations."""
    norm = _normalize(text)
    return norm in _HALLUCINATIONS or len(norm) < 2


def _speakable(text: str) -> str:
    """Drop Markdown/code so TTS doesn't read symbols aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>|~]+", "", text)
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


_YES_RE = re.compile(r"\b(sim|pode|confirmo|confirma|claro|isso|yes|ok|okay)\b")


def is_affirmative(text: str) -> bool:
    norm = _normalize(text)
    if re.search(r"\b(nao|no|cancela|cancelar|negativo)\b", norm):
        return False
    return bool(_YES_RE.search(norm))


# ---------------------------------------------------------------------------
# Event publisher (HTTP → jarvis serve → WebSocket → HUD)
# ---------------------------------------------------------------------------


class VoiceEventPublisher:
    """Fire-and-forget POSTs to ``/v1/voice/events`` on a background thread.

    Never blocks the audio loop: events go through a bounded queue, and level
    events are dropped first when the server is slow or absent.
    """

    def __init__(self, base_url: str | None, api_key: str | None = None) -> None:
        self._url = f"{base_url.rstrip('/')}/v1/voice/events" if base_url else ""
        key = (
            api_key if api_key is not None else os.environ.get("OPENJARVIS_API_KEY", "")
        )
        self._headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._queue: "queue.Queue[Optional[dict]]" = queue.Queue(maxsize=128)
        self._thread: Optional[threading.Thread] = None
        self._warned = False
        if self._url:
            self._thread = threading.Thread(
                target=self._run, name="voice-events", daemon=True
            )
            self._thread.start()

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def emit(self, event_type: str, **data: Any) -> None:
        if not self._url:
            return
        try:
            self._queue.put_nowait({"type": event_type, "data": data})
        except queue.Full:
            pass  # drop: HUD freshness is not worth stalling the mic

    def state(self, state: str, reason: str = "") -> None:
        if reason:
            self.emit("state", state=state, reason=reason)
        else:
            self.emit("state", state=state)

    def _run(self) -> None:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a core dependency
            return
        with httpx.Client(timeout=1.0) as client:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                # Coalesce stale level events so the HUD stays real-time.
                if item["type"] == "level" and not self._queue.empty():
                    continue
                try:
                    client.post(self._url, json=item, headers=self._headers)
                except Exception as exc:
                    if not self._warned:
                        self._warned = True
                        logger.debug("Voice HUD relay unreachable: %s", exc)

    def close(self, timeout: float = 1.5) -> None:
        if self._thread is None:
            return
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            return
        self._thread.join(timeout=timeout)


# ---------------------------------------------------------------------------
# Microphone capture
# ---------------------------------------------------------------------------


def _rms(data: bytes) -> float:
    from openjarvis.speech.voice_io import _rms as voice_rms

    return voice_rms(data)


def measure_ambient(seconds: float = 0.6, device: Any = None) -> float:
    """Return the ambient RMS over ``seconds`` (median of chunks)."""
    import sounddevice as sd

    n_chunks = max(1, int(seconds * _SAMPLE_RATE / _CHUNK))
    values: list[float] = []
    with sd.RawInputStream(
        samplerate=_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=_CHUNK,
        device=device,
    ) as stream:
        for _ in range(n_chunks):
            raw, _ = stream.read(_CHUNK)
            values.append(_rms(bytes(raw)))
    values.sort()
    return values[len(values) // 2]


def threshold_from_ambient(ambient: float) -> float:
    return max(_MIN_THRESHOLD, ambient * _AMBIENT_MULTIPLIER)


def record_utterance(
    *,
    threshold: float,
    wait_seconds: float,
    silence_seconds: float = DEFAULT_SILENCE_SECONDS,
    max_seconds: float = DEFAULT_MAX_UTTERANCE,
    on_level: Optional[Callable[[float], None]] = None,
    device: Any = None,
) -> Optional[bytes]:
    """Wait up to ``wait_seconds`` for speech, then record until silence.

    Returns WAV bytes, or ``None`` if nobody spoke before the wait expired.
    """
    import sounddevice as sd

    from openjarvis.speech.voice_io import _frames_to_wav

    chunks_per_s = _SAMPLE_RATE / _CHUNK
    wait_chunks = max(1, int(wait_seconds * chunks_per_s))
    silence_chunks = max(1, int(silence_seconds * chunks_per_s))
    max_chunks = max(1, int(max_seconds * chunks_per_s))

    preroll: deque[bytes] = deque(maxlen=_PREROLL_CHUNKS)
    frames: list[bytes] = []
    voiced_run = 0
    speaking = False
    silence = 0
    waited = 0
    n = 0

    with sd.RawInputStream(
        samplerate=_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=_CHUNK,
        device=device,
    ) as stream:
        while True:
            raw, _ = stream.read(_CHUNK)
            data = bytes(raw)
            amp = _rms(data)
            n += 1
            if on_level is not None and n % _LEVEL_EVERY_CHUNKS == 0:
                on_level(min(1.0, amp / (threshold * 4.0)))

            if not speaking:
                preroll.append(data)
                voiced_run = voiced_run + 1 if amp > threshold else 0
                if voiced_run >= _MIN_SPEECH_CHUNKS:
                    speaking = True
                    frames.extend(preroll)
                    preroll.clear()
                    continue
                waited += 1
                if waited >= wait_chunks:
                    return None
                continue

            frames.append(data)
            silence = 0 if amp > threshold else silence + 1
            if silence >= silence_chunks or len(frames) >= max_chunks:
                break

    return _frames_to_wav(frames, _SAMPLE_RATE)


def wav_envelope(audio: bytes, step_seconds: float = 0.08) -> tuple[list[float], float]:
    """Normalized RMS envelope of a WAV clip, for the HUD while speaking."""
    import io
    import wave

    try:
        with wave.open(io.BytesIO(audio), "rb") as wf:
            sr = wf.getframerate()
            width = wf.getsampwidth()
            channels = wf.getnchannels()
            pcm = wf.readframes(wf.getnframes())
    except Exception:
        return [], step_seconds
    if width != 2:
        return [], step_seconds
    import struct

    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) // 2 * 2])
    if channels > 1:
        samples = samples[::channels]
    step = max(1, int(sr * step_seconds))
    env = []
    for i in range(0, len(samples), step):
        window = samples[i : i + step]
        if window:
            env.append((sum(s * s for s in window) / len(window)) ** 0.5)
    peak = max(env) if env else 0.0
    if peak <= 0:
        return [0.0 for _ in env], step_seconds
    return [min(1.0, v / peak) for v in env], step_seconds


# ---------------------------------------------------------------------------
# Session controller
# ---------------------------------------------------------------------------


class HandsFreeSession:
    """Drives the turn-taking for one hands-free session.

    ``chat_cmd`` owns the LLM call; this object owns mic, STT, TTS and HUD
    events, and decides when the session is over.
    """

    def __init__(
        self,
        console: Any,
        voice_session: Any,
        *,
        events: VoiceEventPublisher,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        silence_threshold: Optional[float] = None,
        language: Optional[str] = None,
        device: Any = None,
    ) -> None:
        self.console = console
        self.voice = voice_session
        self.events = events
        self.idle_timeout = idle_timeout
        self.language = language or None
        self.device = device
        self._fixed_threshold = silence_threshold
        self.threshold: float = silence_threshold or _MIN_THRESHOLD
        self.end_reason = ""

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._fixed_threshold is None:
            try:
                ambient = measure_ambient(device=self.device)
                self.threshold = threshold_from_ambient(ambient)
                self.console.print(
                    f"[dim]Ruído ambiente RMS≈{ambient:.0f} → limiar de voz "
                    f"{self.threshold:.0f}[/dim]"
                )
            except Exception as exc:
                self.console.print(f"[yellow]Calibração do mic falhou: {exc}[/yellow]")
        # Load Whisper before the first turn so the first answer isn't slow.
        self.voice.get_stt_backend()

    def finish(self, reason: str) -> None:
        self.end_reason = reason
        self.events.state("ended", reason)

    # -- turns --------------------------------------------------------------

    def listen(self) -> Optional[str]:
        """Return the next user utterance, or ``None`` when the session ends.

        Noise/hallucinations are skipped without resetting the idle clock.
        """
        from openjarvis.cli._voice_chat import _terminal_safe_text

        backend = self.voice.get_stt_backend()
        if backend is None:
            self.console.print(
                "[red]Nenhum backend de STT disponível "
                "(uv sync --extra voice / desktop).[/red]"
            )
            self.finish("no_stt")
            return None

        deadline = time.monotonic() + self.idle_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.console.print(
                    "[dim]Silêncio prolongado — encerrando sessão.[/dim]"
                )
                self.finish("idle_timeout")
                return None

            self.events.state("listening")
            self.console.print("[dim cyan]🎙  Ouvindo…[/dim cyan]")
            try:
                audio = record_utterance(
                    threshold=self.threshold,
                    wait_seconds=remaining,
                    on_level=lambda lv: self.events.emit(
                        "level", level=lv, source="listening"
                    ),
                    device=self.device,
                )
            except KeyboardInterrupt:
                self.finish("interrupted")
                return None
            except Exception as exc:
                self.console.print(
                    f"[red]Erro no microfone: {_terminal_safe_text(exc)}[/red]"
                )
                self.finish("mic_error")
                return None

            if audio is None:
                continue  # loop re-checks the deadline and ends the session

            self.events.state("transcribing")
            try:
                result = backend.transcribe(audio, format="wav", language=self.language)
                text = (result.text or "").strip()
            except Exception as exc:
                self.console.print(
                    f"[red]Erro na transcrição: {_terminal_safe_text(exc)}[/red]"
                )
                continue
            if is_noise_transcript(text):
                continue

            self.console.print(f"[bold]Você (voz):[/bold] {_terminal_safe_text(text)}")
            self.events.emit("transcript", text=text)
            if is_exit_phrase(text):
                self.say("Certo. Voltando a ouvir as palmas.")
                self.finish("exit_phrase")
                return None
            return text

    def thinking(self) -> None:
        self.events.state("thinking")

    def say(self, text: str) -> None:
        """Speak ``text`` and stream its envelope to the HUD."""
        from openjarvis.cli._voice_chat import speak

        self.events.emit("response", text=text)
        self.events.state("speaking")
        spoken = _speakable(text)
        if spoken:
            speak(spoken, self.console, self.voice, on_audio=self._stream_envelope)
        # Let the speaker tail die out so the mic doesn't hear our own voice.
        time.sleep(0.25)

    def confirm(self, prompt: str) -> bool:
        """Voice yes/no for destructive tool calls (replaces ``input()``)."""
        self.say(f"Preciso de confirmação: {prompt}. Diga sim ou não.")
        backend = self.voice.get_stt_backend()
        if backend is None:
            return False
        self.events.state("listening", "confirm")
        try:
            audio = record_utterance(
                threshold=self.threshold, wait_seconds=8.0, device=self.device
            )
        except Exception:
            return False
        if audio is None:
            self.say("Sem resposta. Cancelado.")
            return False
        try:
            answer = backend.transcribe(
                audio, format="wav", language=self.language
            ).text
        except Exception:
            return False
        self.events.emit("transcript", text=answer)
        ok = is_affirmative(answer or "")
        self.console.print(
            f"[dim]Confirmação: {answer!r} → {'sim' if ok else 'não'}[/dim]"
        )
        self.events.state("thinking")
        return ok

    def _stream_envelope(self, audio: bytes, _sample_rate: int) -> None:
        if not self.events.enabled:
            return
        env, step = wav_envelope(audio)
        if not env:
            return

        def _pump() -> None:
            start = time.monotonic()
            for i, level in enumerate(env):
                delay = start + i * step - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                self.events.emit("level", level=level, source="speaking")

        threading.Thread(target=_pump, name="voice-envelope", daemon=True).start()


__all__ = [
    "DEFAULT_IDLE_TIMEOUT",
    "HandsFreeSession",
    "VoiceEventPublisher",
    "is_affirmative",
    "is_exit_phrase",
    "is_noise_transcript",
    "record_utterance",
    "threshold_from_ambient",
    "wav_envelope",
]
