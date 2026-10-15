"""Screen reading for the JARVIS HUD: "o que tem na minha tela?".

``POST /api/vision/screen`` captures the screen of the machine running
``jarvis serve`` and extracts its text with the native Windows OCR
(``Windows.Media.Ocr`` — no Tesseract, no vision model). The HUD then asks the
chat model about that text, so it works with any text model.

The endpoint discloses whatever is on screen, so besides the usual API-key
middleware it refuses non-loopback callers when no API key is configured.
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

INSTALL_HINT = "Instale com: uv sync --extra screen (Windows 10+)."
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
MAX_CHARS = 12000


def capture_screen_png(monitor: int = 0) -> tuple[bytes, int, int]:
    """Capture a monitor (0 = all, 1 = primary) as PNG bytes."""
    import mss
    from PIL import Image

    factory = getattr(mss, "MSS", None) or mss.mss
    with factory() as sct:
        monitors = sct.monitors
        target = monitors[monitor] if 0 <= monitor < len(monitors) else monitors[0]
        shot = sct.grab(target)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img.width, img.height


def ocr_png_windows(png: bytes) -> tuple[str, str]:
    """Return ``(text, language_tag)`` using the Windows OCR engine."""
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import (
        DataWriter,
        InMemoryRandomAccessStream,
    )

    async def run() -> tuple[str, str]:
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png)
        await writer.store_async()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError(
                "Nenhum idioma de OCR instalado no Windows "
                "(Configurações → Hora e idioma → Idioma)."
            )
        result = await engine.recognize_async(bitmap)
        lines = [line.text for line in result.lines]
        return "\n".join(lines), engine.recognizer_language.language_tag

    return asyncio.run(run())


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in _LOOPBACK


def create_vision_router(
    *,
    capture: Callable[[int], tuple[bytes, int, int]] = capture_screen_png,
    ocr: Optional[Callable[[bytes], tuple[str, str]]] = None,
) -> APIRouter:
    """Build ``/api/vision/screen``; capture/OCR are injectable for tests."""
    router = APIRouter(prefix="/api/vision", tags=["vision"])
    do_ocr = ocr if ocr is not None else ocr_png_windows

    @router.post("/screen")
    async def read_screen(request: Request) -> Dict[str, Any]:
        if not _is_loopback(request) and not getattr(request.app.state, "api_key", ""):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Leitura de tela só é permitida localmente, ou com "
                    "OPENJARVIS_API_KEY configurada."
                ),
            )
        if ocr is None and sys.platform != "win32":
            raise HTTPException(
                status_code=501, detail="OCR de tela disponível só no Windows."
            )

        def work() -> Dict[str, Any]:
            png, width, height = capture(0)
            text, language = do_ocr(png)
            text = text.strip()
            return {
                "text": text[:MAX_CHARS],
                "truncated": len(text) > MAX_CHARS,
                "chars": len(text),
                "language": language,
                "width": width,
                "height": height,
                "engine": "windows-ocr",
            }

        try:
            return await asyncio.to_thread(work)
        except ImportError as exc:
            raise HTTPException(
                status_code=501, detail=f"{exc}. {INSTALL_HINT}"
            ) from exc
        except Exception as exc:
            logger.warning("Screen read failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router


__all__ = ["capture_screen_png", "create_vision_router", "ocr_png_windows"]
