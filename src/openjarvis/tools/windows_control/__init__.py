"""Windows PC Control Toolkit — JARVIS-level system automation for Windows.

This module provides comprehensive Windows automation capabilities:
- GUI automation (mouse, keyboard, window management)
- System controls (volume, brightness, power, media keys)
- Process & service management
- Screen capture + OCR
- Clipboard access
- File system watching
- Registry access
- Audio device/per-app volume control

Architecture: Python-first for rapid development, with trait-based interfaces
that can be backed by high-performance Rust implementations via PyO3.
"""

from __future__ import annotations

# Re-export all tools for easy registration
from openjarvis.tools.windows_control.gui_automation import (
    MouseTool,
    KeyboardTool,
    WindowManagementTool,
)
from openjarvis.tools.windows_control.system_controls import (
    VolumeControlTool,
    BrightnessControlTool,
    PowerControlTool,
    MediaKeysTool,
)
from openjarvis.tools.windows_control.process_mgmt import (
    ProcessListTool,
    ProcessKillTool,
    ProcessInfoTool,
    ServiceControlTool,
)
from openjarvis.tools.windows_control.screen_capture import (
    ScreenshotTool,
    ScreenOCRTool,
    ScreenRegionTool,
)
from openjarvis.tools.windows_control.clipboard import (
    ClipboardReadTool,
    ClipboardWriteTool,
    ClipboardHistoryTool,
)
from openjarvis.tools.windows_control.filesystem_watch import (
    FileWatchTool,
    FileWatchListTool,
)
from openjarvis.tools.windows_control.registry import (
    RegistryReadTool,
    RegistryWriteTool,
    RegistrySearchTool,
)
from openjarvis.tools.windows_control.audio_control import (
    AudioDeviceListTool,
    AudioDeviceSetDefaultTool,
    AppVolumeControlTool,
    MicrophoneControlTool,
)

__all__ = [
    # GUI Automation
    "MouseTool",
    "KeyboardTool",
    "WindowManagementTool",
    # System Controls
    "VolumeControlTool",
    "BrightnessControlTool",
    "PowerControlTool",
    "MediaKeysTool",
    # Process Management
    "ProcessListTool",
    "ProcessKillTool",
    "ProcessInfoTool",
    "ServiceControlTool",
    # Screen Capture + OCR
    "ScreenshotTool",
    "ScreenOCRTool",
    "ScreenRegionTool",
    # Clipboard
    "ClipboardReadTool",
    "ClipboardWriteTool",
    "ClipboardHistoryTool",
    # File System Watch
    "FileWatchTool",
    "FileWatchListTool",
    # Registry
    "RegistryReadTool",
    "RegistryWriteTool",
    "RegistrySearchTool",
    # Audio Control
    "AudioDeviceListTool",
    "AudioDeviceSetDefaultTool",
    "AppVolumeControlTool",
    "MicrophoneControlTool",
]

# Tool categories for the registry
WINDOWS_CONTROL_CATEGORIES = {
    "gui": "GUI Automation",
    "system": "System Controls",
    "process": "Process Management",
    "screen": "Screen Capture",
    "clipboard": "Clipboard",
    "filesystem": "File System",
    "registry": "Registry",
    "audio": "Audio Control",
}