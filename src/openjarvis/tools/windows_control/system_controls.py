"""System Controls Tools — Volume, Brightness, Power, Media Keys for Windows.

Provides JARVIS-level system control:
- Volume: get/set system volume, mute/unmute
- Brightness: get/set display brightness (laptop/monitor)
- Power: sleep, hibernate, shutdown, restart, lock
- Media Keys: play/pause, next/prev track, volume up/down/mute
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


# ---------------------------------------------------------------------------
# Volume Control Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("volume")
class VolumeControlTool(BaseTool):
    """Control system volume: get/set volume level, mute/unmute."""

    tool_id = "volume"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="volume",
            description=(
                "Controla o volume do sistema: obter/definir nível (0-100), "
                "mutar/desmutar, aumentar/diminuir volume."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "mute", "unmute", "toggle_mute", "up", "down"],
                        "description": "Ação a executar",
                    },
                    "level": {"type": "integer", "description": "Nível de volume (0-100) para 'set'"},
                    "step": {"type": "integer", "description": "Passo para up/down (padrão: 10)", "default": 10},
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=False,
            required_capabilities=["system:audio"],
        )

    def _run_powershell(self, script: str) -> tuple[bool, str]:
        """Run PowerShell script and return (success, output)."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "Timeout executando PowerShell"
        except Exception as exc:
            return False, str(exc)

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        level = params.get("level")
        step = params.get("step", 10)

        try:
            if action == "get":
                script = """
                Add-Type -TypeDefinition @"
                using System;
                using System.Runtime.InteropServices;
                public class Audio {
                    [DllImport("winmm.dll")] public static extern int waveOutGetVolume(IntPtr hwo, out uint pdwVolume);
                    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(IntPtr hwo, uint dwVolume);
                }
"@
                $vol = 0
                [Audio]::waveOutGetVolume([IntPtr]::Zero, [ref]$vol) | Out-Null
                $left = $vol -band 0xFFFF
                $right = ($vol -shr 16) -band 0xFFFF
                $avg = (($left + $right) / 2) / 65535 * 100
                [math]::Round($avg)
                """
                success, output = self._run_powershell(script)
                if success:
                    vol = int(output) if output.isdigit() else 0
                    return ToolResult(
                        tool_name="volume",
                        content=f"Volume atual: {vol}%",
                        success=True,
                        metadata={"level": vol},
                    )

            elif action == "set":
                if level is None:
                    return ToolResult(tool_name="volume", content="Ação 'set' requer 'level' (0-100)", success=False)
                level = max(0, min(100, level))
                # Convert 0-100 to 0-65535
                vol_val = int(level / 100 * 65535)
                vol_val = (vol_val << 16) | vol_val  # Both channels (compute in Python)
                script = f"""
                Add-Type -TypeDefinition @"
                using System;
                using System.Runtime.InteropServices;
                public class Audio {{
                    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(IntPtr hwo, uint dwVolume);
                }}
"@
                [Audio]::waveOutSetVolume([IntPtr]::Zero, {vol_val}) | Out-Null
                """
                success, output = self._run_powershell(script)
                if success:
                    return ToolResult(
                        tool_name="volume",
                        content=f"Volume definido para {level}%",
                        success=True,
                        metadata={"level": level},
                    )

            elif action in ("mute", "unmute", "toggle_mute"):
                # Use SendKeys for mute toggle (VK_VOLUME_MUTE = 0xAD)
                script = """
                $wshell = New-Object -ComObject WScript.Shell
                $wshell.SendKeys([char]0xAD)
                """
                success, output = self._run_powershell(script)
                if success:
                    state = "mutado" if action in ("mute", "toggle_mute") else "desmutado"
                    return ToolResult(
                        tool_name="volume",
                        content=f"Volume {state}",
                        success=True,
                        metadata={"muted": action in ("mute", "toggle_mute")},
                    )

            elif action in ("up", "down"):
                # Use media keys for volume up/down
                key = 0xAF if action == "up" else 0xAE  # VK_VOLUME_UP / VK_VOLUME_DOWN
                script = f"""
                $wshell = New-Object -ComObject WScript.Shell
                for ($i = 0; $i -lt {step/2}; $i++) {{
                    $wshell.SendKeys([char]{key})
                }}
                """
                success, output = self._run_powershell(script)
                if success:
                    return ToolResult(
                        tool_name="volume",
                        content=f"Volume {'aumentado' if action == 'up' else 'diminuído'} em {step} passos",
                        success=True,
                        metadata={"direction": action, "steps": step},
                    )

            return ToolResult(
                tool_name="volume",
                content=f"Ação desconhecida: {action}",
                success=False,
            )

        except Exception as exc:
            return ToolResult(
                tool_name="volume",
                content=f"Erro no controle de volume: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Brightness Control Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("brightness")
class BrightnessControlTool(BaseTool):
    """Control display brightness: get/set brightness level (0-100)."""

    tool_id = "brightness"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="brightness",
            description=(
                "Controla o brilho da tela: obter/definir nível (0-100). "
                "Funciona em laptops e monitores com suporte DDC/CI."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "up", "down"],
                        "description": "Ação a executar",
                    },
                    "level": {"type": "integer", "description": "Nível de brilho (0-100) para 'set'"},
                    "step": {"type": "integer", "description": "Passo para up/down (padrão: 10)", "default": 10},
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=False,
            required_capabilities=["system:display"],
        )

    def _run_wmi(self, namespace: str, query: str) -> tuple[bool, Any]:
        """Run WMI query via PowerShell."""
        script = f"Get-WmiObject -Namespace '{namespace}' -Query \"{query}\" | Select-Object *"
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as exc:
            return False, str(exc)

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        level = params.get("level")
        step = params.get("step", 10)

        try:
            if action == "get":
                # Try WMI first (laptop internal display)
                success, output = self._run_wmi(
                    "root/WMI", "SELECT CurrentBrightness FROM WmiMonitorBrightness"
                )
                if success and output:
                    lines = output.split("\n")
                    for line in lines:
                        if "CurrentBrightness" in line:
                            val = int(line.split(":")[-1].strip())
                            return ToolResult(
                                tool_name="brightness",
                                content=f"Brilho atual: {val}%",
                                success=True,
                                metadata={"level": val},
                            )

                # Fallback: try Get-CimInstance
                script = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", script],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip().isdigit():
                    val = int(result.stdout.strip())
                    return ToolResult(
                        tool_name="brightness",
                        content=f"Brilho atual: {val}%",
                        success=True,
                        metadata={"level": val},
                    )

                return ToolResult(
                    tool_name="brightness",
                    content="Não foi possível obter brilho (monitor pode não suportar)",
                    success=False,
                )

            elif action == "set":
                if level is None:
                    return ToolResult(tool_name="brightness", content="Ação 'set' requer 'level' (0-100)", success=False)
                level = max(0, min(100, level))
                script = f"""
                $monitors = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods
                foreach ($m in $monitors) {{
                    $m.WmiSetBrightness(1, {level})
                }}
                """
                success, output = self._run_powershell(script)
                if success:
                    return ToolResult(
                        tool_name="brightness",
                        content=f"Brilho definido para {level}%",
                        success=True,
                        metadata={"level": level},
                    )

            elif action in ("up", "down"):
                # Get current then adjust
                get_result = self.execute(action="get")
                if get_result.success:
                    current = get_result.metadata.get("level", 50)
                    new_level = current + step if action == "up" else current - step
                    new_level = max(0, min(100, new_level))
                    return self.execute(action="set", level=new_level)
                return ToolResult(tool_name="brightness", content="Não foi possível obter brilho atual", success=False)

            return ToolResult(
                tool_name="brightness",
                content=f"Ação desconhecida: {action}",
                success=False,
            )

        except Exception as exc:
            return ToolResult(
                tool_name="brightness",
                content=f"Erro no controle de brilho: {exc}",
                success=False,
            )

    def _run_powershell(self, script: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as exc:
            return False, str(exc)


# ---------------------------------------------------------------------------
# Power Control Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("power")
class PowerControlTool(BaseTool):
    """Control system power: sleep, hibernate, shutdown, restart, lock."""

    tool_id = "power"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="power",
            description=(
                "Controla energia do sistema: suspender, hibernar, desligar, "
                "reiniciar, bloquear tela. Requer confirmação para ações destrutivas."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["sleep", "hibernate", "shutdown", "restart", "lock", "abort_shutdown"],
                        "description": "Ação de energia a executar",
                    },
                    "force": {"type": "boolean", "description": "Forçar fechamento de apps (shutdown/restart)", "default": False},
                    "delay": {"type": "integer", "description": "Atraso em segundos antes de executar", "default": 0},
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=True,
            required_capabilities=["system:power"],
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        force = params.get("force", False)
        delay = params.get("delay", 0)

        # Ações perigosas requerem confirmação extra
        dangerous = action in ("shutdown", "restart", "hibernate")
        if dangerous and not force:
            return ToolResult(
                tool_name="power",
                content=f"Ação '{action}' é destrutiva. Use force=true para confirmar.",
                success=False,
            )

        try:
            if delay > 0:
                import time
                time.sleep(delay)

            if action == "sleep":
                # Suspender (standby)
                subprocess.run(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                    check=False
                )
                return ToolResult(
                    tool_name="power",
                    content="Sistema entrando em suspensão...",
                    success=True,
                )

            elif action == "hibernate":
                # Hibernar
                subprocess.run(
                    ["rundll32.exe", "powrprof.dll,SetSuspendState", "1,1,0"],
                    check=False
                )
                return ToolResult(
                    tool_name="power",
                    content="Sistema hibernando...",
                    success=True,
                )

            elif action == "shutdown":
                flags = "/s /t 0"
                if force:
                    flags += " /f"
                subprocess.run(["shutdown"] + flags.split(), check=False)
                return ToolResult(
                    tool_name="power",
                    content="Desligando o sistema...",
                    success=True,
                )

            elif action == "restart":
                flags = "/r /t 0"
                if force:
                    flags += " /f"
                subprocess.run(["shutdown"] + flags.split(), check=False)
                return ToolResult(
                    tool_name="power",
                    content="Reiniciando o sistema...",
                    success=True,
                )

            elif action == "lock":
                # Bloquear estação de trabalho
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return ToolResult(
                    tool_name="power",
                    content="Tela bloqueada",
                    success=True,
                )

            elif action == "abort_shutdown":
                subprocess.run(["shutdown", "/a"], check=False)
                return ToolResult(
                    tool_name="power",
                    content="Desligamento/reinício cancelado",
                    success=True,
                )

            return ToolResult(
                tool_name="power",
                content=f"Ação desconhecida: {action}",
                success=False,
            )

        except Exception as exc:
            return ToolResult(
                tool_name="power",
                content=f"Erro no controle de energia: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Media Keys Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("media_keys")
class MediaKeysTool(BaseTool):
    """Send media key presses: play/pause, next/prev track, volume, stop."""

    tool_id = "media_keys"

    # Virtual key codes for media keys
    VK_MEDIA_PLAY_PAUSE = 0xB3
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_UP = 0xAF
    VK_VOLUME_DOWN = 0xAE

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="media_keys",
            description=(
                "Envia teclas de mídia: play/pause, próxima/anterior faixa, "
                "parar, volume, mute. Funciona com qualquer player (Spotify, YouTube, etc.)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play_pause", "next", "prev", "previous", "stop", "volume_up", "volume_down", "mute"],
                        "description": "Tecla de mídia a enviar",
                    },
                    "repeat": {"type": "integer", "description": "Repetir a tecla N vezes (para volume)", "default": 1},
                },
                "required": ["action"],
            },
            category="system",
            requires_confirmation=False,
            required_capabilities=["system:audio"],
        )

    def _send_key(self, vk_code: int) -> bool:
        """Send a virtual key via SendInput."""
        try:
            import ctypes
            from ctypes import wintypes

            # Define structures
            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", wintypes.ULONG_PTR),
                ]

            class INPUT(ctypes.Structure):
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("ki", KEYBDINPUT),
                ]

            # Send key down
            input_down = INPUT()
            input_down.type = 1  # INPUT_KEYBOARD
            input_down.ki.wVk = vk_code
            input_down.ki.dwFlags = 0

            # Send key up
            input_up = INPUT()
            input_up.type = 1
            input_up.ki.wVk = vk_code
            input_up.ki.dwFlags = 2  # KEYEVENTF_KEYUP

            ctypes.windll.user32.SendInput(1, ctypes.byref(input_down), ctypes.sizeof(INPUT))
            ctypes.windll.user32.SendInput(1, ctypes.byref(input_up), ctypes.sizeof(INPUT))
            return True
        except Exception:
            return False

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        repeat = params.get("repeat", 1)

        key_map = {
            "play_pause": self.VK_MEDIA_PLAY_PAUSE,
            "next": self.VK_MEDIA_NEXT_TRACK,
            "prev": self.VK_MEDIA_PREV_TRACK,
            "previous": self.VK_MEDIA_PREV_TRACK,
            "stop": self.VK_MEDIA_STOP,
            "volume_up": self.VK_VOLUME_UP,
            "volume_down": self.VK_VOLUME_DOWN,
            "mute": self.VK_VOLUME_MUTE,
        }

        if action not in key_map:
            return ToolResult(
                tool_name="media_keys",
                content=f"Ação desconhecida: {action}",
                success=False,
            )

        vk = key_map[action]
        success_count = 0
        for _ in range(repeat):
            if self._send_key(vk):
                success_count += 1
            import time
            time.sleep(0.05)

        action_names = {
            "play_pause": "Play/Pause",
            "next": "Próxima faixa",
            "prev": "Faixa anterior",
            "previous": "Faixa anterior",
            "stop": "Parar",
            "volume_up": "Volume +",
            "volume_down": "Volume -",
            "mute": "Mute",
        }

        return ToolResult(
            tool_name="media_keys",
            content=f"{action_names.get(action, action)} enviado ({success_count}/{repeat}x)",
            success=success_count > 0,
            metadata={"action": action, "sent": success_count, "requested": repeat},
        )