#!/usr/bin/env python
"""
Test script for Windows PC Control Toolkit.
Run this to verify all tools are working correctly.
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_imports():
    """Test that all tools can be imported."""
    print("=" * 60)
    print("Testing Windows Control Toolkit Imports")
    print("=" * 60)

    tools_to_test = [
        ("GUI Automation", "openjarvis.tools.windows_control.gui_automation"),
        ("System Controls", "openjarvis.tools.windows_control.system_controls"),
        ("Process Management", "openjarvis.tools.windows_control.process_mgmt"),
        ("Screen Capture", "openjarvis.tools.windows_control.screen_capture"),
        ("Clipboard", "openjarvis.tools.windows_control.clipboard"),
        ("File System Watch", "openjarvis.tools.windows_control.filesystem_watch"),
        ("Registry", "openjarvis.tools.windows_control.registry"),
        ("Audio Control", "openjarvis.tools.windows_control.audio_control"),
    ]

    all_passed = True
    for category, mod in tools_to_test:
        try:
            module = __import__(mod, fromlist=['*'])
            print(f"\n{category}: [OK] {mod}")
            # Check for expected classes
            expected_classes = [c for c in dir(module) if c.endswith('Tool') and not c.startswith('_')]
            for cls_name in expected_classes:
                print(f"  [OK] {mod}.{cls_name}")
        except ImportError as e:
            print(f"\n{category}: [FAIL] {mod} - {e}")
            all_passed = False

    return all_passed


def test_registry():
    """Test that tools are registered in the ToolRegistry."""
    print("\n" + "=" * 60)
    print("Testing Tool Registry Registration")
    print("=" * 60)

    from openjarvis.core.registry import ToolRegistry

    expected_tools = [
        "mouse", "keyboard", "window",
        "volume", "brightness", "power", "media_keys",
        "process_list", "process_kill", "process_info", "service",
        "screenshot", "screen_ocr", "screen_region",
        "clipboard_read", "clipboard_write", "clipboard_history",
        "file_watch", "file_watch_list",
        "registry_read", "registry_write", "registry_search",
        "audio_device_list", "audio_device_set_default", "app_volume", "microphone",
    ]

    registered = ToolRegistry.keys()
    print(f"Total registered tools: {len(registered)}")

    missing = []
    for tool in expected_tools:
        if tool in registered:
            print(f"  [OK] {tool}")
        else:
            print(f"  [FAIL] {tool} - NOT REGISTERED")
            missing.append(tool)

    if missing:
        print(f"\nMissing tools: {missing}")
        return False
    return True


async def test_basic_execution():
    """Test basic execution of safe tools."""
    print("\n" + "=" * 60)
    print("Testing Basic Tool Execution")
    print("=" * 60)

    from openjarvis.core.registry import ToolRegistry
    from openjarvis.core.types import ToolResult

    # Test tools that don't require special permissions
    safe_tests = [
        ("process_list", {"action": "list", "limit": 5}),
        ("volume", {"action": "get"}),
        ("brightness", {"action": "get"}),
        ("audio_device_list", {"type": "all"}),
        ("clipboard_read", {"format": "text"}),
        ("registry_read", {"key": "HKCU\\Environment", "value": ""}),
        ("service", {"action": "list"}),
    ]

    for tool_name, params in safe_tests:
        try:
            tool_class = ToolRegistry.get(tool_name)
            if tool_class:
                tool = tool_class()
                result = tool.execute(**params)
                status = "[OK]" if result.success else "[WARN]"
                print(f"  {status} {tool_name}: {result.content[:80]}...")
            else:
                print(f"  [FAIL] {tool_name}: Not found in registry")
        except Exception as e:
            print(f"  [FAIL] {tool_name}: {e}")

    return True


def test_optional_dependencies():
    """Check which optional dependencies are installed."""
    print("\n" + "=" * 60)
    print("Checking Optional Dependencies")
    print("=" * 60)

    deps = {
        "pyautogui": "GUI Automation (mouse/keyboard)",
        "pygetwindow": "Window Management",
        "pywinauto": "Advanced Windows Automation",
        "uiautomation": "UI Automation (modern Windows)",
        "mss": "Fast Screenshots",
        "PIL": "Image Processing (Pillow)",
        "pytesseract": "OCR (Tesseract)",
        "watchdog": "File System Watching",
        "cv2": "Computer Vision (OpenCV)",
        "pycaw": "Windows Core Audio API",
        "comtypes": "COM Types for pycaw",
    }

    for dep, desc in deps.items():
        try:
            __import__(dep)
            print(f"  [OK] {dep} - {desc}")
        except ImportError:
            print(f"  [ ] {dep} - {desc} (NOT INSTALLED)")


def main():
    print("\n[OpenJarvis] Windows PC Control Toolkit - Test Suite")
    print("=" * 60)

    # Test imports
    imports_ok = test_imports()

    # Test registry
    registry_ok = test_registry()

    # Check dependencies
    test_optional_dependencies()

    # Test basic execution
    asyncio.run(test_basic_execution())

    if imports_ok and registry_ok:
        print("\n[OK] All core tests PASSED!")
        print("\nTo install optional dependencies:")
        print("  uv sync --extra windows-control")
        print("  # or")
        print("  pip install -e '.[windows-control]'")
    else:
        print("\n[FAIL] Some tests FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()