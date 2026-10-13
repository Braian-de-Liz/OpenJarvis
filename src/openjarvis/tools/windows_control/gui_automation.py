"""GUI Automation Tools — Mouse, Keyboard, and Window Management for Windows.

Provides JARVIS-level control over Windows GUI:
- Mouse: move, click, drag, scroll, position
- Keyboard: type, hotkeys, key press/release, text input
- Windows: list, focus, move, resize, minimize/maximize, close, get info

Uses pyautogui/pygetwindow for cross-platform compatibility with Windows optimizations.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Helper: Lazy imports for optional dependencies
# ---------------------------------------------------------------------------

def _get_pyautogui():
    """Lazy import pyautogui with helpful error."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = True  # Move mouse to corner to abort
        pyautogui.PAUSE = 0.01     # Small delay between actions
        return pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui não instalado. Instale com: uv sync --extra gui-automation\n"
            "Ou: pip install pyautogui pygetwindow"
        )

def _get_pywinauto():
    """Lazy import pywinauto for advanced Windows automation."""
    try:
        import pywinauto
        return pywinauto
    except ImportError:
        raise ImportError(
            "pywinauto não instalado. Instale com: pip install pywinauto"
        )

def _get_uiautomation():
    """Lazy import uiautomation for UI Automation (modern Windows)."""
    try:
        import uiautomation as auto
        return auto
    except ImportError:
        raise ImportError(
            "uiautomation não instalado. Instale com: pip install uiautomation"
        )


# ---------------------------------------------------------------------------
# Mouse Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("mouse")
class MouseTool(BaseTool):
    """Control mouse: move, click, drag, scroll, get position."""

    tool_id = "mouse"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="mouse",
            description=(
                "Controla o mouse: mover, clicar, arrastar, rolar, obter posição. "
                "Suporta coordenadas absolutas e relativas."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["move", "click", "double_click", "right_click", "drag", "scroll", "position"],
                        "description": "Ação a executar",
                    },
                    "x": {"type": "integer", "description": "Coordenada X (absoluta ou relativa)"},
                    "y": {"type": "integer", "description": "Coordenada Y (absoluta ou relativa)"},
                    "relative": {"type": "boolean", "description": "Se true, coordenadas são relativas à posição atual", "default": False},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Botão do mouse", "default": "left"},
                    "clicks": {"type": "integer", "description": "Número de cliques", "default": 1},
                    "interval": {"type": "number", "description": "Intervalo entre cliques (segundos)", "default": 0.1},
                    "duration": {"type": "number", "description": "Duração do movimento/arraste (segundos)", "default": 0.5},
                    "amount": {"type": "integer", "description": "Quantidade de rolagem (positivo = cima, negativo = baixo)"},
                },
                "required": ["action"],
            },
            category="gui",
            requires_confirmation=True,
            required_capabilities=["gui:control"],
        )

    def execute(self, **params: Any) -> ToolResult:
        pg = _get_pyautogui()
        action = params.get("action", "")

        try:
            if action == "position":
                x, y = pg.position()
                return ToolResult(
                    tool_name="mouse",
                    content=f"Posição atual do mouse: ({x}, {y})",
                    success=True,
                    metadata={"x": x, "y": y},
                )

            x = params.get("x")
            y = params.get("y")
            relative = params.get("relative", False)
            button = params.get("button", "left")
            clicks = params.get("clicks", 1)
            interval = params.get("interval", 0.1)
            duration = params.get("duration", 0.5)

            if action in ("move", "click", "double_click", "right_click", "drag"):
                if x is None or y is None:
                    return ToolResult(
                        tool_name="mouse",
                        content=f"Ação '{action}' requer coordenadas x e y",
                        success=False,
                    )

                target_x, target_y = (x, y)
                if relative:
                    cur_x, cur_y = pg.position()
                    target_x, target_y = cur_x + x, cur_y + y

            if action == "move":
                pg.moveTo(target_x, target_y, duration=duration)
                return ToolResult(
                    tool_name="mouse",
                    content=f"Mouse movido para ({target_x}, {target_y})",
                    success=True,
                    metadata={"x": target_x, "y": target_y},
                )

            elif action == "click":
                pg.click(target_x, target_y, clicks=clicks, interval=interval, button=button, duration=duration)
                return ToolResult(
                    tool_name="mouse",
                    content=f"Clicou {clicks}x em ({target_x}, {target_y}) com botão {button}",
                    success=True,
                    metadata={"x": target_x, "y": target_y, "clicks": clicks, "button": button},
                )

            elif action == "double_click":
                pg.doubleClick(target_x, target_y, interval=interval, button=button, duration=duration)
                return ToolResult(
                    tool_name="mouse",
                    content=f"Duplo clique em ({target_x}, {target_y})",
                    success=True,
                    metadata={"x": target_x, "y": target_y, "button": button},
                )

            elif action == "right_click":
                pg.rightClick(target_x, target_y, duration=duration)
                return ToolResult(
                    tool_name="mouse",
                    content=f"Clique direito em ({target_x}, {target_y})",
                    success=True,
                    metadata={"x": target_x, "y": target_y},
                )

            elif action == "drag":
                pg.dragTo(target_x, target_y, duration=duration, button=button)
                return ToolResult(
                    tool_name="mouse",
                    content=f"Arrastou para ({target_x}, {target_y})",
                    success=True,
                    metadata={"x": target_x, "y": target_y, "button": button},
                )

            elif action == "scroll":
                amount = params.get("amount", 0)
                if x is not None and y is not None:
                    pg.moveTo(x, y, duration=0.1)
                pg.scroll(amount)
                direction = "cima" if amount > 0 else "baixo"
                return ToolResult(
                    tool_name="mouse",
                    content=f"Rolou {abs(amount)} cliques para {direction}",
                    success=True,
                    metadata={"amount": amount},
                )

            else:
                return ToolResult(
                    tool_name="mouse",
                    content=f"Ação desconhecida: {action}",
                    success=False,
                )

        except Exception as exc:
            return ToolResult(
                tool_name="mouse",
                content=f"Erro no mouse: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Keyboard Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("keyboard")
class KeyboardTool(BaseTool):
    """Control keyboard: type text, press keys, hotkeys, key combinations."""

    tool_id = "keyboard"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="keyboard",
            description=(
                "Controla o teclado: digitar texto, pressionar teclas, atalhos (hotkeys), "
                "combinações de teclas (Ctrl+C, Alt+Tab, Win+D, etc.)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["type", "press", "hotkey", "key_down", "key_up", "write"],
                        "description": "Ação a executar",
                    },
                    "text": {"type": "string", "description": "Texto para digitar (para 'type' e 'write')"},
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "Lista de teclas para 'press', 'hotkey', 'key_down', 'key_up'"},
                    "interval": {"type": "number", "description": "Intervalo entre caracteres (segundos)", "default": 0.01},
                },
                "required": ["action"],
            },
            category="gui",
            requires_confirmation=True,
            required_capabilities=["gui:control"],
        )

    def execute(self, **params: Any) -> ToolResult:
        pg = _get_pyautogui()
        action = params.get("action", "")

        try:
            if action == "type":
                text = params.get("text", "")
                if not text:
                    return ToolResult(tool_name="keyboard", content="Nenhum texto fornecido", success=False)
                interval = params.get("interval", 0.01)
                pg.write(text, interval=interval)
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Digitou: {text[:50]}{'...' if len(text) > 50 else ''}",
                    success=True,
                    metadata={"length": len(text)},
                )

            elif action == "write":
                # write é alias para type mas sem intervalo padrão
                text = params.get("text", "")
                if not text:
                    return ToolResult(tool_name="keyboard", content="Nenhum texto fornecido", success=False)
                pg.write(text)
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Escreveu: {text[:50]}{'...' if len(text) > 50 else ''}",
                    success=True,
                    metadata={"length": len(text)},
                )

            elif action == "press":
                keys = params.get("keys", [])
                if not keys:
                    return ToolResult(tool_name="keyboard", content="Nenhuma tecla fornecida", success=False)
                for key in keys:
                    pg.press(key)
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Pressionou teclas: {', '.join(keys)}",
                    success=True,
                    metadata={"keys": keys},
                )

            elif action == "hotkey":
                keys = params.get("keys", [])
                if not keys:
                    return ToolResult(tool_name="keyboard", content="Nenhuma tecla fornecida para hotkey", success=False)
                pg.hotkey(*keys)
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Executou hotkey: {'+'.join(keys)}",
                    success=True,
                    metadata={"keys": keys},
                )

            elif action == "key_down":
                keys = params.get("keys", [])
                if not keys:
                    return ToolResult(tool_name="keyboard", content="Nenhuma tecla fornecida", success=False)
                for key in keys:
                    pg.keyDown(key)
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Pressionou e segurou: {', '.join(keys)}",
                    success=True,
                    metadata={"keys": keys},
                )

            elif action == "key_up":
                keys = params.get("keys", [])
                if not keys:
                    return ToolResult(tool_name="keyboard", content="Nenhuma tecla fornecida", success=False)
                for key in keys:
                    pg.keyUp(key)
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Liberou teclas: {', '.join(keys)}",
                    success=True,
                    metadata={"keys": keys},
                )

            else:
                return ToolResult(
                    tool_name="keyboard",
                    content=f"Ação desconhecida: {action}",
                    success=False,
                )

        except Exception as exc:
            return ToolResult(
                tool_name="keyboard",
                content=f"Erro no teclado: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Window Management Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("window")
class WindowManagementTool(BaseTool):
    """Manage Windows windows: list, focus, move, resize, minimize, maximize, close, get info."""

    tool_id = "window"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="window",
            description=(
                "Gerencia janelas do Windows: listar, focar, mover, redimensionar, "
                "minimizar/maximizar, fechar, obter informações (título, posição, tamanho, processo)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "focus", "move", "resize", "minimize", "maximize", "restore", "close", "get_info", "get_active", "set_title"],
                        "description": "Ação a executar",
                    },
                    "title": {"type": "string", "description": "Título da janela (parcial ou completo)"},
                    "hwnd": {"type": "integer", "description": "Handle da janela (HWND)"},
                    "x": {"type": "integer", "description": "Nova posição X"},
                    "y": {"type": "integer", "description": "Nova posição Y"},
                    "width": {"type": "integer", "description": "Nova largura"},
                    "height": {"type": "integer", "description": "Nova altura"},
                    "filter": {"type": "string", "description": "Filtrar janelas por título (para list)"},
                },
                "required": ["action"],
            },
            category="gui",
            requires_confirmation=True,
            required_capabilities=["gui:control"],
        )

    def _find_window(self, title: Optional[str] = None, hwnd: Optional[int] = None):
        """Find window by title or HWND using pygetwindow."""
        try:
            import pygetwindow as gw
        except ImportError:
            raise ImportError("pygetwindow não instalado. Instale com: pip install pygetwindow")

        if hwnd:
            try:
                win = gw._pygetwindow_win.getWindow(hwnd)
                if win:
                    return win
            except Exception:
                pass

        if title:
            windows = gw.getWindowsWithTitle(title)
            if windows:
                return windows[0]

        return None

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        title = params.get("title")
        hwnd = params.get("hwnd")

        try:
            import pygetwindow as gw

            if action == "list":
                filter_text = params.get("filter", "")
                windows = gw.getAllWindows()
                result = []
                for w in windows:
                    if not filter_text or filter_text.lower() in w.title.lower():
                        result.append({
                            "hwnd": w._hWnd,
                            "title": w.title,
                            "left": w.left,
                            "top": w.top,
                            "width": w.width,
                            "height": w.height,
                            "visible": w.visible,
                            "minimized": w.isMinimized,
                            "maximized": w.isMaximized,
                            "active": w.isActive,
                        })
                return ToolResult(
                    tool_name="window",
                    content=f"Encontradas {len(result)} janelas",
                    success=True,
                    metadata={"windows": result, "count": len(result)},
                )

            elif action == "get_active":
                active = gw.getActiveWindow()
                if active:
                    return ToolResult(
                        tool_name="window",
                        content=f"Janela ativa: {active.title}",
                        success=True,
                        metadata={
                            "hwnd": active._hWnd,
                            "title": active.title,
                            "left": active.left,
                            "top": active.top,
                            "width": active.width,
                            "height": active.height,
                        },
                    )
                return ToolResult(tool_name="window", content="Nenhuma janela ativa", success=False)

            win = self._find_window(title, hwnd)
            if not win:
                return ToolResult(
                    tool_name="window",
                    content=f"Janela não encontrada: title='{title}', hwnd={hwnd}",
                    success=False,
                )

            if action == "focus":
                win.activate()
                return ToolResult(
                    tool_name="window",
                    content=f"Focou na janela: {win.title}",
                    success=True,
                    metadata={"hwnd": win._hWnd, "title": win.title},
                )

            elif action == "move":
                x = params.get("x")
                y = params.get("y")
                if x is None or y is None:
                    return ToolResult(tool_name="window", content="Ação 'move' requer x e y", success=False)
                win.moveTo(x, y)
                return ToolResult(
                    tool_name="window",
                    content=f"Moveu janela '{win.title}' para ({x}, {y})",
                    success=True,
                    metadata={"hwnd": win._hWnd, "x": x, "y": y},
                )

            elif action == "resize":
                width = params.get("width")
                height = params.get("height")
                if width is None or height is None:
                    return ToolResult(tool_name="window", content="Ação 'resize' requer width e height", success=False)
                win.resizeTo(width, height)
                return ToolResult(
                    tool_name="window",
                    content=f"Redimensionou janela '{win.title}' para {width}x{height}",
                    success=True,
                    metadata={"hwnd": win._hWnd, "width": width, "height": height},
                )

            elif action == "minimize":
                win.minimize()
                return ToolResult(
                    tool_name="window",
                    content=f"Minimizou janela: {win.title}",
                    success=True,
                    metadata={"hwnd": win._hWnd},
                )

            elif action == "maximize":
                win.maximize()
                return ToolResult(
                    tool_name="window",
                    content=f"Maximizou janela: {win.title}",
                    success=True,
                    metadata={"hwnd": win._hWnd},
                )

            elif action == "restore":
                win.restore()
                return ToolResult(
                    tool_name="window",
                    content=f"Raugurou janela: {win.title}",
                    success=True,
                    metadata={"hwnd": win._hWnd},
                )

            elif action == "close":
                win.close()
                return ToolResult(
                    tool_name="window",
                    content=f"Fechou janela: {win.title}",
                    success=True,
                    metadata={"hwnd": win._hWnd},
                )

            elif action == "get_info":
                return ToolResult(
                    tool_name="window",
                    content=f"Info da janela: {win.title}",
                    success=True,
                    metadata={
                        "hwnd": win._hWnd,
                        "title": win.title,
                        "left": win.left,
                        "top": win.top,
                        "width": win.width,
                        "height": win.height,
                        "visible": win.visible,
                        "minimized": win.isMinimized,
                        "maximized": win.isMaximized,
                        "active": win.isActive,
                    },
                )

            elif action == "set_title":
                # Requires pywinauto for setting title
                pw = _get_pywinauto()
                app = pw.Application().connect(handle=win._hWnd)
                app.window(handle=win._hWnd).set_window_text(params.get("title", ""))
                return ToolResult(
                    tool_name="window",
                    content=f"Título alterado (requer pywinauto)",
                    success=True,
                )

            else:
                return ToolResult(
                    tool_name="window",
                    content=f"Ação desconhecida: {action}",
                    success=False,
                )

        except ImportError as exc:
            return ToolResult(
                tool_name="window",
                content=f"Dependência faltando: {exc}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="window",
                content=f"Erro na janela: {exc}",
                success=False,
            )