#!/usr/bin/env python
"""
JARVIS Windows Control - Interactive Demo
Run this to see the Windows control tools in action.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from openjarvis.core.registry import ToolRegistry
from openjarvis.sdk import OpenJarvis


async def demo_gui_automation(jarvis):
    """Demo: GUI Automation"""
    print("\n🎮 === GUI AUTOMATION DEMO ===")
    
    # Get mouse position
    result = await jarvis.tools.mouse.execute(action="position")
    print(f"Mouse position: {result.content}")
    
    # List windows
    result = await jarvis.tools.window.execute(action="list", filter="", limit=5)
    print(f"Top windows:\n{result.content}")


async def demo_system_controls(jarvis):
    """Demo: System Controls"""
    print("\n🔧 === SYSTEM CONTROLS DEMO ===")
    
    # Volume
    result = await jarvis.tools.volume.execute(action="get")
    print(f"Volume: {result.content}")
    
    # Brightness
    result = await jarvis.tools.brightness.execute(action="get")
    print(f"Brightness: {result.content}")
    
    # Media keys (safe - just shows what would happen)
    print("Media keys available: play_pause, next, prev, stop, volume_up, volume_down, mute")


async def demo_process_mgmt(jarvis):
    """Demo: Process Management"""
    print("\n⚙️ === PROCESS MANAGEMENT DEMO ===")
    
    # List top CPU processes
    result = await jarvis.tools.process_list.execute(limit=10, sort_by="cpu")
    print(f"Top processes:\n{result.content}")


async def demo_screen_capture(jarvis):
    """Demo: Screen Capture & OCR"""
    print("\n📸 === SCREEN CAPTURE DEMO ===")
    
    # Take screenshot
    result = await jarvis.tools.screenshot.execute(mode="full", return_base64=False, save_path="~/jarvis_demo_screenshot.png")
    print(f"Screenshot: {result.content}")
    
    if result.success and "saved_path" in result.metadata:
        # OCR on screenshot
        ocr_result = await jarvis.tools.screen_ocr.execute(source="file", file_path=result.metadata["saved_path"])
        print(f"OCR result (first 200 chars): {ocr_result.content[:200]}...")


async def demo_clipboard(jarvis):
    """Demo: Clipboard"""
    print("\n📋 === CLIPBOARD DEMO ===")
    
    # Write to clipboard
    await jarvis.tools.clipboard_write.execute(text="Hello from JARVIS! 🤖")
    print("Wrote to clipboard")
    
    # Read back
    result = await jarvis.tools.clipboard_read.execute(format="text")
    print(f"Clipboard content: {result.content}")


async def demo_registry(jarvis):
    """Demo: Registry"""
    print("\n🗂️ === REGISTRY DEMO ===")
    
    # Read environment variables
    result = await jarvis.tools.registry_read.execute(key="HKCU\\Environment")
    print(f"User environment variables:\n{result.content}")


async def demo_audio(jarvis):
    """Demo: Audio Control"""
    print("\n🔊 === AUDIO CONTROL DEMO ===")
    
    # List audio devices
    result = await jarvis.tools.audio_device_list.execute(type="all")
    print(f"Audio devices:\n{result.content}")


async def demo_file_watch(jarvis):
    """Demo: File System Watch"""
    print("\n👁️ === FILE SYSTEM WATCH DEMO ===")
    
    # Start watching a directory
    result = await jarvis.tools.file_watch.execute(
        action="start",
        path="~/Downloads",
        patterns=["*.pdf", "*.docx", "*.txt"],
        watch_id="downloads_watcher"
    )
    print(f"Watcher started: {result.content}")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Get events
    result = await jarvis.tools.file_watch.execute(action="get_events", watch_id="downloads_watcher")
    print(f"Events: {result.content}")
    
    # Stop watcher
    await jarvis.tools.file_watch.execute(action="stop", watch_id="downloads_watcher")
    print("Watcher stopped")


async def main():
    print("🤖 JARVIS Windows Control - Interactive Demo")
    print("=" * 50)
    
    # Initialize JARVIS
    jarvis = OpenJarvis()
    
    # Check available tools
    tools = ToolRegistry.list_tools()
    windows_tools = [t for t in tools if any(cat in t for cat in ["mouse", "keyboard", "window", "volume", "brightness", "power", "media", "process", "screenshot", "screen_", "clipboard", "file_watch", "registry", "audio"])]
    print(f"\nAvailable Windows tools: {len(windows_tools)}")
    for t in sorted(windows_tools):
        print(f"  • {t}")
    
    print("\n⚠️  This demo runs SAFE read-only operations.")
    print("   Destructive actions (click, kill, shutdown, write) are skipped.")
    
    # Run demos
    try:
        await demo_gui_automation(jarvis)
        await demo_system_controls(jarvis)
        await demo_process_mgmt(jarvis)
        await demo_screen_capture(jarvis)
        await demo_clipboard(jarvis)
        await demo_registry(jarvis)
        await demo_audio(jarvis)
        await demo_file_watch(jarvis)
    except Exception as e:
        print(f"\n❌ Demo error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 50)
    print("✅ Demo completed!")
    print("\nTo use in your own code:")
    print("  from openjarvis.sdk import OpenJarvis")
    print("  jarvis = OpenJarvis()")
    print("  await jarvis.tools.mouse.execute(action='click', x=100, y=100)")
    print("\nSee WINDOWS_CONTROL_GUIDE.md for full examples!")


if __name__ == "__main__":
    asyncio.run(main())