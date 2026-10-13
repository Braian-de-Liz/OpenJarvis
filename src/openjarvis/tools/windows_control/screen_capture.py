"""Screen Capture & OCR Tools — Screenshot, Region Capture, Text Extraction for Windows.

Provides JARVIS-level screen interaction:
- Full screen / window / region screenshots
- Save to file or return as base64
- OCR (Optical Character Recognition) via Tesseract or Windows OCR
- Screen region selection and analysis
"""

from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


# ---------------------------------------------------------------------------
# Screenshot Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("screenshot")
class ScreenshotTool(BaseTool):
    """Capture screenshots: full screen, specific window, or region. Returns base64 or saves to file."""

    tool_id = "screenshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screenshot",
            description=(
                "Captura de tela: tela cheia, janela específica ou região. "
                "Retorna base64 ou salva em arquivo. Suporta PNG/JPG."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["full", "window", "region", "monitor"], "description": "Modo de captura", "default": "full"},
                    "window_title": {"type": "string", "description": "Título da janela (para mode='window')"},
                    "hwnd": {"type": "integer", "description": "Handle da janela (HWND)"},
                    "x": {"type": "integer", "description": "X da região (para mode='region')"},
                    "y": {"type": "integer", "description": "Y da região"},
                    "width": {"type": "integer", "description": "Largura da região"},
                    "height": {"type": "integer", "description": "Altura da região"},
                    "monitor": {"type": "integer", "description": "Índice do monitor (0=principal, para mode='monitor')", "default": 0},
                    "save_path": {"type": "string", "description": "Caminho para salvar arquivo (opcional)"},
                    "format": {"type": "string", "enum": ["png", "jpg", "jpeg"], "description": "Formato da imagem", "default": "png"},
                    "quality": {"type": "integer", "description": "Qualidade JPG (1-100)", "default": 90},
                    "return_base64": {"type": "boolean", "description": "Retornar imagem como base64", "default": True},
                },
                "required": [],
            },
            category="screen",
            requires_confirmation=False,
            required_capabilities=["gui:capture"],
        )

    def _get_mss(self):
        """Lazy import mss (fast cross-platform screenshot)."""
        try:
            import mss
            return mss
        except ImportError:
            raise ImportError("mss não instalado. Instale com: pip install mss")

    def _get_pil(self):
        """Lazy import PIL/Pillow."""
        try:
            from PIL import Image
            return Image
        except ImportError:
            raise ImportError("Pillow não instalado. Instale com: pip install pillow")

    def execute(self, **params: Any) -> ToolResult:
        mode = params.get("mode", "full")
        window_title = params.get("window_title")
        hwnd = params.get("hwnd")
        x = params.get("x")
        y = params.get("y")
        width = params.get("width")
        height = params.get("height")
        monitor_idx = params.get("monitor", 0)
        save_path = params.get("save_path")
        fmt = params.get("format", "png")
        quality = params.get("quality", 90)
        return_base64 = params.get("return_base64", True)

        try:
            mss = self._get_mss()
            Image = self._get_pil()

            with mss.mss() as sct:
                if mode == "full":
                    # Capture all monitors
                    monitor = sct.monitors[0]  # All monitors combined
                    screenshot = sct.grab(monitor)

                elif mode == "monitor":
                    monitors = sct.monitors[1:]  # Skip index 0 (all combined)
                    if monitor_idx >= len(monitors):
                        return ToolResult(
                            tool_name="screenshot",
                            content=f"Monitor {monitor_idx} não existe. Disponíveis: {len(monitors)}",
                            success=False,
                        )
                    monitor = monitors[monitor_idx]
                    screenshot = sct.grab(monitor)

                elif mode == "window":
                    if not window_title and not hwnd:
                        return ToolResult(
                            tool_name="screenshot",
                            content="Para mode='window', forneça 'window_title' ou 'hwnd'",
                            success=False,
                        )
                    import pygetwindow as gw
                    win = None
                    if hwnd:
                        try:
                            win = gw._pygetwindow_win.getWindow(hwnd)
                        except Exception:
                            pass
                    if not win and window_title:
                        wins = gw.getWindowsWithTitle(window_title)
                        if wins:
                            win = wins[0]
                    if not win:
                        return ToolResult(
                            tool_name="screenshot",
                            content=f"Janela não encontrada: title='{window_title}', hwnd={hwnd}",
                            success=False,
                        )
                    # Get window rect
                    left, top, right, bottom = win.left, win.top, win.right, win.bottom
                    monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
                    screenshot = sct.grab(monitor)

                elif mode == "region":
                    if x is None or y is None or width is None or height is None:
                        return ToolResult(
                            tool_name="screenshot",
                            content="Para mode='region', forneça x, y, width, height",
                            success=False,
                        )
                    monitor = {"left": x, "top": y, "width": width, "height": height}
                    screenshot = sct.grab(monitor)

                else:
                    return ToolResult(
                        tool_name="screenshot",
                        content=f"Modo desconhecido: {mode}",
                        success=False,
                    )

            # Convert to PIL Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            # Save to file if requested
            saved_path = None
            if save_path:
                path = Path(save_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if fmt.lower() in ("jpg", "jpeg"):
                    img.save(path, format="JPEG", quality=quality)
                else:
                    img.save(path, format="PNG")
                saved_path = str(path.resolve())

            # Convert to base64 if requested
            b64_data = None
            if return_base64:
                buffer = io.BytesIO()
                if fmt.lower() in ("jpg", "jpeg"):
                    img.save(buffer, format="JPEG", quality=quality)
                else:
                    img.save(buffer, format="PNG")
                b64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")

            metadata = {
                "mode": mode,
                "width": img.width,
                "height": img.height,
                "format": fmt,
            }
            if saved_path:
                metadata["saved_path"] = saved_path

            content = f"Screenshot capturado: {img.width}x{img.height} ({mode})"
            if saved_path:
                content += f"\nSalvo em: {saved_path}"

            return ToolResult(
                tool_name="screenshot",
                content=content,
                success=True,
                metadata=metadata,
            )

        except ImportError as exc:
            return ToolResult(
                tool_name="screenshot",
                content=f"Dependência faltando: {exc}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="screenshot",
                content=f"Erro ao capturar tela: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Screen OCR Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("screen_ocr")
class ScreenOCRTool(BaseTool):
    """Extract text from screen using OCR: full screen, window, region, or image file."""

    tool_id = "screen_ocr"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_ocr",
            description=(
                "Extrai texto da tela via OCR: tela cheia, janela, região ou arquivo de imagem. "
                "Suporta Tesseract (local) e Windows OCR (nativo Win10+)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "enum": ["screen", "window", "region", "file"], "description": "Fonte da imagem", "default": "screen"},
                    "window_title": {"type": "string", "description": "Título da janela (para source='window')"},
                    "hwnd": {"type": "integer", "description": "Handle da janela"},
                    "x": {"type": "integer", "description": "X da região"},
                    "y": {"type": "integer", "description": "Y da região"},
                    "width": {"type": "integer", "description": "Largura da região"},
                    "height": {"type": "integer", "description": "Altura da região"},
                    "file_path": {"type": "string", "description": "Caminho do arquivo de imagem (para source='file')"},
                    "engine": {"type": "string", "enum": ["tesseract", "windows", "auto"], "description": "Engine OCR a usar", "default": "auto"},
                    "lang": {"type": "string", "description": "Idioma(s) para OCR (ex: 'por', 'eng', 'por+eng')", "default": "por+eng"},
                    "preprocess": {"type": "boolean", "description": "Pré-processar imagem (escala de cinza, threshold)", "default": True},
                },
                "required": [],
            },
            category="screen",
            requires_confirmation=False,
            required_capabilities=["gui:capture", "ai:ocr"],
        )

    def _capture_image(self, source: str, **kwargs):
        """Capture image based on source. Returns PIL Image."""
        Image = None
        try:
            from PIL import Image
        except ImportError:
            raise ImportError("Pillow não instalado. Instale com: pip install pillow")

        if source == "screen":
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb)

        elif source == "window":
            import pygetwindow as gw
            win = None
            if kwargs.get("hwnd"):
                try:
                    win = gw._pygetwindow_win.getWindow(kwargs["hwnd"])
                except Exception:
                    pass
            if not win and kwargs.get("window_title"):
                wins = gw.getWindowsWithTitle(kwargs["window_title"])
                if wins:
                    win = wins[0]
            if not win:
                raise ValueError(f"Janela não encontrada: title='{kwargs.get('window_title')}', hwnd={kwargs.get('hwnd')}")
            import mss
            with mss.mss() as sct:
                monitor = {"left": win.left, "top": win.top, "width": win.width, "height": win.height}
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb)

        elif source == "region":
            x, y, w, h = kwargs.get("x"), kwargs.get("y"), kwargs.get("width"), kwargs.get("height")
            if None in (x, y, w, h):
                raise ValueError("Região requer x, y, width, height")
            import mss
            with mss.mss() as sct:
                monitor = {"left": x, "top": y, "width": w, "height": h}
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb)

        elif source == "file":
            path = kwargs.get("file_path")
            if not path:
                raise ValueError("source='file' requer 'file_path'")
            return Image.open(path)

        raise ValueError(f"Fonte desconhecida: {source}")

    def _preprocess(self, img, preprocess: bool):
        """Preprocess image for better OCR."""
        if not preprocess:
            return img
        try:
            # Convert to grayscale
            img = img.convert("L")
            # Increase contrast
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            # Threshold
            img = img.point(lambda x: 0 if x < 128 else 255)
            return img
        except Exception:
            return img

    def _ocr_tesseract(self, img, lang: str):
        """OCR using Tesseract."""
        try:
            import pytesseract
            return pytesseract.image_to_string(img, lang=lang)
        except ImportError:
            raise ImportError("pytesseract não instalado. Instale com: pip install pytesseract\nTambém instale Tesseract: winget install UB-Mannheim.TesseractOCR")

    def _ocr_windows(self, img, lang: str):
        """OCR using Windows Runtime API (Win10+)."""
        try:
            import winrt.windows.media.ocr as ocr
            import winrt.windows.graphics.imaging as imaging
            import winrt.windows.storage.streams as streams
            import asyncio

            # Convert PIL to Windows bitmap
            from PIL import Image
            import io

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)

            async def do_ocr():
                # Create decoder
                decoder = await imaging.BitmapDecoder.create_async(
                    imaging.BitmapDecoder.png_decoder_id,
                    streams.InMemoryRandomAccessStream(buffer.getvalue())
                )
                # Get software bitmap
                software_bitmap = await decoder.get_software_bitmap_async()
                # Create OCR engine
                ocr_engine = ocr.OcrEngine.try_create_from_language(
                    ocr.Language(lang.split("+")[0])  # Windows OCR takes single language
                )
                if not ocr_engine:
                    return "Windows OCR não suporta este idioma"
                result = await ocr_engine.recognize_async(software_bitmap)
                lines = []
                for line in result.lines:
                    lines.append(line.text)
                return "\n".join(lines)

            return asyncio.run(do_ocr())

        except ImportError:
            raise ImportError("winrt não instalado. Instale com: pip install winrt")
        except Exception as exc:
            return f"Erro no Windows OCR: {exc}"

    def execute(self, **params: Any) -> ToolResult:
        source = params.get("source", "screen")
        engine = params.get("engine", "auto")
        lang = params.get("lang", "por+eng")
        preprocess = params.get("preprocess", True)

        try:
            # Capture image - exclude source from params to avoid duplicate
            capture_params = {k: v for k, v in params.items() if k != 'source'}
            img = self._capture_image(source, **capture_params)

            # Preprocess
            img = self._preprocess(img, preprocess)

            # Select engine
            if engine == "auto":
                # Try Windows OCR first (faster, no extra install), fallback to Tesseract
                try:
                    text = self._ocr_windows(img, lang.split("+")[0])
                    if text and not text.startswith("Erro") and not text.startswith("Windows OCR não suporta"):
                        engine_used = "windows"
                    else:
                        text = self._ocr_tesseract(img, lang)
                        engine_used = "tesseract"
                except Exception:
                    text = self._ocr_tesseract(img, lang)
                    engine_used = "tesseract"
            elif engine == "windows":
                text = self._ocr_windows(img, lang.split("+")[0])
                engine_used = "windows"
            else:  # tesseract
                text = self._ocr_tesseract(img, lang)
                engine_used = "tesseract"

            # Clean up text
            text = text.strip()
            if not text:
                text = "(nenhum texto detectado)"

            return ToolResult(
                tool_name="screen_ocr",
                content=text,
                success=True,
                metadata={
                    "engine": engine_used,
                    "language": lang,
                    "source": source,
                    "char_count": len(text),
                },
            )

        except ImportError as exc:
            return ToolResult(
                tool_name="screen_ocr",
                content=f"Dependência faltando: {exc}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="screen_ocr",
                content=f"Erro no OCR: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Screen Region Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("screen_region")
class ScreenRegionTool(BaseTool):
    """Analyze screen regions: find colors, locate images, get pixel data."""

    tool_id = "screen_region"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_region",
            description=(
                "Analisa regiões da tela: obter cor do pixel, encontrar cor, "
                "localizar imagem na tela (template matching), obter histogramas."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get_pixel", "find_color", "find_image", "histogram", "average_color"],
                        "description": "Ação a executar",
                    },
                    "x": {"type": "integer", "description": "Coordenada X"},
                    "y": {"type": "integer", "description": "Coordenada Y"},
                    "region": {"type": "array", "items": {"type": "integer"}, "description": "Região [x, y, width, height]"},
                    "color": {"type": "array", "items": {"type": "integer"}, "description": "Cor RGB alvo [r, g, b]"},
                    "tolerance": {"type": "integer", "description": "Tolerância para busca de cor (0-255)", "default": 10},
                    "template_path": {"type": "string", "description": "Caminho da imagem template (para find_image)"},
                    "threshold": {"type": "number", "description": "Threshold para template matching (0-1)", "default": 0.8},
                },
                "required": ["action"],
            },
            category="screen",
            requires_confirmation=False,
            required_capabilities=["gui:capture"],
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        x = params.get("x")
        y = params.get("y")
        region = params.get("region")
        color = params.get("color")
        tolerance = params.get("tolerance", 10)
        template_path = params.get("template_path")
        threshold = params.get("threshold", 0.8)

        try:
            import mss
            from PIL import Image
            import numpy as np

            # Capture region or full screen
            if region:
                rx, ry, rw, rh = region
                monitor = {"left": rx, "top": ry, "width": rw, "height": rh}
            else:
                with mss.mss() as sct:
                    monitor = sct.monitors[0]

            with mss.mss() as sct:
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.rgb)
                img_np = np.array(img)

            if action == "get_pixel":
                if x is None or y is None:
                    return ToolResult(tool_name="screen_region", content="get_pixel requer x e y", success=False)
                # Adjust for region offset
                px = x - (region[0] if region else 0)
                py = y - (region[1] if region else 0)
                if 0 <= px < img.width and 0 <= py < img.height:
                    pixel = img_np[py, px]
                    return ToolResult(
                        tool_name="screen_region",
                        content=f"Pixel ({x}, {y}): RGB({pixel[0]}, {pixel[1]}, {pixel[2]})",
                        success=True,
                        metadata={"x": x, "y": y, "rgb": pixel.tolist()},
                    )
                return ToolResult(tool_name="screen_region", content="Coordenadas fora da região capturada", success=False)

            elif action == "average_color":
                if region:
                    avg = img_np.mean(axis=(0, 1))
                else:
                    # Sample center region
                    h, w = img_np.shape[:2]
                    cx, cy = w // 2, h // 2
                    sample = img_np[cy-50:cy+50, cx-50:cx+50]
                    avg = sample.mean(axis=(0, 1))
                return ToolResult(
                    tool_name="screen_region",
                    content=f"Cor média: RGB({avg[0]:.0f}, {avg[1]:.0f}, {avg[2]:.0f})",
                    success=True,
                    metadata={"rgb": avg.tolist()},
                )

            elif action == "find_color":
                if not color:
                    return ToolResult(tool_name="screen_region", content="find_color requer 'color' [r,g,b]", success=False)
                target = np.array(color)
                diff = np.abs(img_np.astype(int) - target).max(axis=2)
                matches = np.where(diff <= tolerance)
                coords = list(zip(matches[1].tolist(), matches[0].tolist()))  # x, y
                if region:
                    coords = [(x + region[0], y + region[1]) for x, y in coords]
                return ToolResult(
                    tool_name="screen_region",
                    content=f"Encontrados {len(coords)} pixels com cor {color} (tolerância {tolerance})",
                    success=True,
                    metadata={"matches": coords[:100], "count": len(coords)},
                )

            elif action == "find_image":
                if not template_path:
                    return ToolResult(tool_name="screen_region", content="find_image requer 'template_path'", success=False)
                try:
                    import cv2
                except ImportError:
                    return ToolResult(tool_name="screen_region", content="opencv-python não instalado. Instale com: pip install opencv-python", success=False)

                template = cv2.imread(template_path, cv2.IMREAD_COLOR)
                if template is None:
                    return ToolResult(tool_name="screen_region", content=f"Não foi possível carregar template: {template_path}", success=False)

                screen_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                result = cv2.matchTemplate(screen_cv, template, cv2.TM_CCOEFF_NORMED)
                locations = np.where(result >= threshold)
                matches = []
                for pt in zip(*locations[::-1]):
                    mx, my = pt
                    if region:
                        mx += region[0]
                        my += region[1]
                    matches.append({"x": int(mx), "y": int(my), "confidence": float(result[pt[1], pt[0]])})

                return ToolResult(
                    tool_name="screen_region",
                    content=f"Encontradas {len(matches)} correspondências para template (threshold={threshold})",
                    success=True,
                    metadata={"matches": matches, "count": len(matches)},
                )

            elif action == "histogram":
                hist_r = np.histogram(img_np[:, :, 0], bins=256, range=(0, 256))[0].tolist()
                hist_g = np.histogram(img_np[:, :, 1], bins=256, range=(0, 256))[0].tolist()
                hist_b = np.histogram(img_np[:, :, 2], bins=256, range=(0, 256))[0].tolist()
                return ToolResult(
                    tool_name="screen_region",
                    content=f"Histograma calculado para região {img.width}x{img.height}",
                    success=True,
                    metadata={"histogram": {"r": hist_r, "g": hist_g, "b": hist_b}},
                )

            return ToolResult(
                tool_name="screen_region",
                content=f"Ação desconhecida: {action}",
                success=False,
            )

        except ImportError as exc:
            return ToolResult(
                tool_name="screen_region",
                content=f"Dependência faltando: {exc}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="screen_region",
                content=f"Erro na análise de região: {exc}",
                success=False,
            )