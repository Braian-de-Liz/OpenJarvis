"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]

try:
    import ctranslate2
except ImportError:
    ctranslate2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_CUDA_PRELOADED = False


def _preload_cuda_libs() -> None:
    """Load cuBLAS from the ``nvidia-cublas-cu12`` wheel on Windows.

    CTranslate2 ships cuDNN but not cuBLAS, and it loads ``cublas64_12.dll``
    by name, so Windows never looks inside ``site-packages/nvidia``
    (``os.add_dll_directory`` does not help either). Loading the DLLs by full
    path first makes the later by-name lookup hit the module already in
    memory. Best effort: without the wheel, the CPU fallback still applies.
    """
    global _CUDA_PRELOADED
    if _CUDA_PRELOADED or sys.platform != "win32":
        return
    _CUDA_PRELOADED = True
    import ctypes
    import site

    for root in site.getsitepackages():
        bin_dir = os.path.join(root, "nvidia", "cublas", "bin")
        if not os.path.isdir(bin_dir):
            continue
        # cublas64_12 depends on cublasLt64_12, so load that first.
        for name in ("cublasLt64_12.dll", "cublas64_12.dll"):
            path = os.path.join(bin_dir, name)
            if os.path.isfile(path):
                try:
                    ctypes.WinDLL(path)
                except OSError as exc:
                    logger.debug("Could not preload %s: %s", path, exc)
        return


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._last_error: Optional[str] = None

    def _resolve_compute_type(self) -> str:
        """Pick a CTranslate2 compute type supported by the configured device."""
        if ctranslate2 is None:
            return self._compute_type

        try:
            supported = set(ctranslate2.get_supported_compute_types(self._device))
        except Exception as exc:
            logger.debug(
                "Could not inspect CTranslate2 compute types for %s: %s",
                self._device,
                exc,
            )
            return self._compute_type

        if self._compute_type in supported:
            return self._compute_type

        preferences = (
            ("int8", "float32", "int8_float32", "int16")
            if self._compute_type == "float16"
            else ("float32", "int8", "int8_float32", "int16")
        )
        fallback = next((value for value in preferences if value in supported), None)
        if fallback is None:
            return self._compute_type

        logger.warning(
            "CTranslate2 compute_type=%r is not supported on device=%r; "
            "using %r instead",
            self._compute_type,
            self._device,
            fallback,
        )
        return fallback

    def _should_fallback_to_cpu(self, exc: Exception) -> bool:
        """True for missing-CUDA-runtime errors when the device was not forced."""
        if self._device != "auto":
            return False  # explicit cpu/cuda request: surface the error
        msg = str(exc).lower()
        return any(token in msg for token in ("cublas", "cudnn", "cuda", "libcudart"))

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                self._last_error = (
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra desktop"
                )
                raise ImportError(self._last_error)
            if self._device != "cpu":
                _preload_cuda_libs()
            compute_type = self._resolve_compute_type()
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=compute_type,
            )
        self._last_error = None
        return self._model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        try:
            model = self._ensure_model()

            # Write audio to a temp file (faster-whisper needs a file path).
            # delete=False + manual unlink: on Windows an open
            # NamedTemporaryFile holds an exclusive handle, so PyAV's reopen
            # of tmp.name inside model.transcribe() fails with EACCES.
            suffix = f".{format}" if not format.startswith(".") else format
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                with tmp:
                    tmp.write(audio)

                kwargs = {}
                if language:
                    kwargs["language"] = language

                try:
                    segments_iter, info = model.transcribe(tmp.name, **kwargs)
                    segments_list = list(segments_iter)
                except RuntimeError as exc:
                    # device="auto" picks CUDA whenever a GPU is visible, but the
                    # CUDA runtime DLLs (cuBLAS/cuDNN) are often missing on
                    # Windows; the failure only surfaces at first inference.
                    if not self._should_fallback_to_cpu(exc):
                        raise
                    logger.warning(
                        "Faster-Whisper GPU inference failed (%s); using CPU", exc
                    )
                    self._device = "cpu"
                    self._compute_type = "int8"
                    self._model = None
                    model = self._ensure_model()
                    segments_iter, info = model.transcribe(tmp.name, **kwargs)
                    segments_list = list(segments_iter)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError as unlink_exc:
                    logger.debug(
                        "Could not remove temp audio file %s: %s",
                        tmp.name,
                        unlink_exc,
                    )
        except Exception as exc:
            self._last_error = str(exc)
            raise

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        self._last_error = None
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        try:
            self._ensure_model()
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug("Faster-Whisper health check failed: %s", exc)
            return False

    def last_error(self) -> Optional[str]:
        """Return the last model load or transcription error, if any."""
        return self._last_error

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
