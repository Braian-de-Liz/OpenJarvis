"""File System Watch Tools — Real-time file system monitoring for Windows.

Provides JARVIS-level file system event monitoring:
- Watch directories for changes (create, modify, delete, rename)
- Filter by file patterns
- Get events in real-time or poll for batch
- List active watchers
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


# ---------------------------------------------------------------------------
# Global watcher state
# ---------------------------------------------------------------------------

_watchers: Dict[str, Dict] = {}
_watchers_lock = threading.Lock()


def _get_watcher(watch_id: str) -> Optional[Dict]:
    with _watchers_lock:
        return _watchers.get(watch_id)


def _add_watcher(watch_id: str, info: Dict) -> None:
    with _watchers_lock:
        _watchers[watch_id] = info


def _remove_watcher(watch_id: str) -> bool:
    with _watchers_lock:
        if watch_id in _watchers:
            del _watchers[watch_id]
            return True
        return False


def _list_watchers() -> List[Dict]:
    with _watchers_lock:
        return [{"id": k, **v} for k, v in _watchers.items()]


# ---------------------------------------------------------------------------
# File Watch Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("file_watch")
class FileWatchTool(BaseTool):
    """Start/stop file system watchers for real-time directory monitoring."""

    tool_id = "file_watch"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_watch",
            description=(
                "Monitora sistema de arquivos em tempo real: cria, modifica, deleta, renomeia. "
                "Suporta filtros por padrão, recursivo, e buffer de eventos."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "get_events", "clear_events"],
                        "description": "Ação no watcher",
                        "default": "start",
                    },
                    "watch_id": {"type": "string", "description": "ID único do watcher (auto-gerado se omitido)"},
                    "path": {"type": "string", "description": "Diretório a monitorar (para start)"},
                    "recursive": {"type": "boolean", "description": "Monitorar subdiretórios", "default": True},
                    "patterns": {"type": "array", "items": {"type": "string"}, "description": "Padrões de arquivo (ex: ['*.txt', '*.py'])", "default": ["*"]},
                    "ignore_patterns": {"type": "array", "items": {"type": "string"}, "description": "Padrões para ignorar", "default": []},
                    "events": {"type": "array", "items": {"type": "string", "enum": ["created", "modified", "deleted", "moved"]}, "description": "Tipos de evento a capturar", "default": ["created", "modified", "deleted", "moved"]},
                    "max_events": {"type": "integer", "description": "Máximo de eventos no buffer", "default": 1000},
                },
                "required": [],
            },
            category="filesystem",
            requires_confirmation=False,
            required_capabilities=["file:watch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "start")
        watch_id = params.get("watch_id")
        path = params.get("path")
        recursive = params.get("recursive", True)
        patterns = params.get("patterns", ["*"])
        ignore_patterns = params.get("ignore_patterns", [])
        events = params.get("events", ["created", "modified", "deleted", "moved"])
        max_events = params.get("max_events", 1000)

        try:
            if action == "start":
                if not path:
                    return ToolResult(
                        tool_name="file_watch",
                        content="Ação 'start' requer 'path'",
                        success=False,
                    )

                p = Path(path).resolve()
                if not p.exists() or not p.is_dir():
                    return ToolResult(
                        tool_name="file_watch",
                        content=f"Diretório não encontrado: {path}",
                        success=False,
                    )

                # Generate watch_id if not provided
                if not watch_id:
                    watch_id = f"watch_{len(_watchers) + 1}_{int(time.time())}"

                # Try to use watchdog (cross-platform)
                try:
                    from watchdog.observers import Observer
                    from watchdog.events import FileSystemEventHandler, PatternMatchingEventHandler
                except ImportError:
                    return ToolResult(
                        tool_name="file_watch",
                        content="watchdog não instalado. Instale com: pip install watchdog",
                        success=False,
                    )

                # Create event buffer
                event_buffer = []
                buffer_lock = threading.Lock()

                class BufferedHandler(PatternMatchingEventHandler):
                    def __init__(self):
                        super().__init__(
                            patterns=patterns,
                            ignore_patterns=ignore_patterns,
                            ignore_directories=False,
                            case_sensitive=False,
                        )

                    def _add_event(self, event_type: str, src_path: str, dest_path: str = None):
                        with buffer_lock:
                            event = {
                                "type": event_type,
                                "path": src_path,
                                "time": time.time(),
                            }
                            if dest_path:
                                event["dest_path"] = dest_path
                            event_buffer.append(event)
                            # Trim buffer
                            if len(event_buffer) > max_events:
                                event_buffer.pop(0)

                    def on_created(self, event):
                        if "created" in events:
                            self._add_event("created", event.src_path)

                    def on_modified(self, event):
                        if "modified" in events:
                            self._add_event("modified", event.src_path)

                    def on_deleted(self, event):
                        if "deleted" in events:
                            self._add_event("deleted", event.src_path)

                    def on_moved(self, event):
                        if "moved" in events:
                            self._add_event("moved", event.src_path, event.dest_path)

                handler = BufferedHandler()
                observer = Observer()
                observer.schedule(handler, str(p), recursive=recursive)
                observer.start()

                _add_watcher(watch_id, {
                    "path": str(p),
                    "recursive": recursive,
                    "patterns": patterns,
                    "ignore_patterns": ignore_patterns,
                    "events": events,
                    "observer": observer,
                    "handler": handler,
                    "buffer": event_buffer,
                    "buffer_lock": buffer_lock,
                    "started": time.time(),
                })

                return ToolResult(
                    tool_name="file_watch",
                    content=f"Watcher '{watch_id}' iniciado em {p}",
                    success=True,
                    metadata={"watch_id": watch_id, "path": str(p)},
                )

            elif action == "stop":
                if not watch_id:
                    return ToolResult(
                        tool_name="file_watch",
                        content="Ação 'stop' requer 'watch_id'",
                        success=False,
                    )

                watcher = _get_watcher(watch_id)
                if not watcher:
                    return ToolResult(
                        tool_name="file_watch",
                        content=f"Watcher não encontrado: {watch_id}",
                        success=False,
                    )

                watcher["observer"].stop()
                watcher["observer"].join(timeout=5)
                _remove_watcher(watch_id)

                return ToolResult(
                    tool_name="file_watch",
                    content=f"Watcher '{watch_id}' parado",
                    success=True,
                    metadata={"watch_id": watch_id},
                )

            elif action == "get_events":
                if not watch_id:
                    return ToolResult(
                        tool_name="file_watch",
                        content="Ação 'get_events' requer 'watch_id'",
                        success=False,
                    )

                watcher = _get_watcher(watch_id)
                if not watcher:
                    return ToolResult(
                        tool_name="file_watch",
                        content=f"Watcher não encontrado: {watch_id}",
                        success=False,
                    )

                with watcher["buffer_lock"]:
                    events_copy = watcher["buffer"].copy()

                # Format events
                lines = [f"Eventos do watcher '{watch_id}' ({len(events_copy)} total):"]
                for e in events_copy[-50:]:  # Show last 50
                    t = time.strftime("%H:%M:%S", time.localtime(e["time"]))
                    if e["type"] == "moved":
                        lines.append(f"  [{t}] {e['type']}: {e['path']} -> {e.get('dest_path', '?')}")
                    else:
                        lines.append(f"  [{t}] {e['type']}: {e['path']}")

                return ToolResult(
                    tool_name="file_watch",
                    content="\n".join(lines),
                    success=True,
                    metadata={"watch_id": watch_id, "events": events_copy, "count": len(events_copy)},
                )

            elif action == "clear_events":
                if not watch_id:
                    return ToolResult(
                        tool_name="file_watch",
                        content="Ação 'clear_events' requer 'watch_id'",
                        success=False,
                    )

                watcher = _get_watcher(watch_id)
                if not watcher:
                    return ToolResult(
                        tool_name="file_watch",
                        content=f"Watcher não encontrado: {watch_id}",
                        success=False,
                    )

                with watcher["buffer_lock"]:
                    watcher["buffer"].clear()

                return ToolResult(
                    tool_name="file_watch",
                    content=f"Buffer de eventos do watcher '{watch_id}' limpo",
                    success=True,
                    metadata={"watch_id": watch_id},
                )

            return ToolResult(
                tool_name="file_watch",
                content=f"Ação desconhecida: {action}",
                success=False,
            )

        except Exception as exc:
            return ToolResult(
                tool_name="file_watch",
                content=f"Erro no file watch: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# File Watch List Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("file_watch_list")
class FileWatchListTool(BaseTool):
    """List all active file system watchers."""

    tool_id = "file_watch_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_watch_list",
            description="Lista todos os watchers de sistema de arquivos ativos.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            category="filesystem",
            requires_confirmation=False,
            required_capabilities=["file:watch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        watchers = _list_watchers()

        if not watchers:
            return ToolResult(
                tool_name="file_watch_list",
                content="Nenhum watcher ativo",
                success=True,
                metadata={"watchers": []},
            )

        lines = [f"Watchers ativos ({len(watchers)}):"]
        for w in watchers:
            uptime = time.time() - w["started"]
            lines.append(
                f"  {w['id']}: {w['path']} (recursive={w['recursive']}, "
                f"patterns={w['patterns']}, uptime={uptime:.0f}s)"
            )

        return ToolResult(
            tool_name="file_watch_list",
            content="\n".join(lines),
            success=True,
            metadata={"watchers": watchers},
        )