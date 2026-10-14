"""Voice session event relay: CLI voice loop → HTTP → WebSocket → HUD.

The hands-free voice loop (``jarvis show`` / ``jarvis chat --hands-free``)
runs in its own process, so it cannot publish on the server's in-process
``EventBus``. Instead it POSTs small JSON events to ``/v1/voice/events`` and
this module fans them out to every browser connected on ``/v1/voice/ws``.

Both endpoints live under ``/v1`` so they inherit ``AuthMiddleware`` (HTTP)
and ``authenticate_websocket`` (WS) when ``OPENJARVIS_API_KEY`` is set.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

VoiceEventType = Literal["state", "transcript", "response", "level", "tool", "session"]

VOICE_STATES = frozenset(
    {
        "idle",  # waiting for claps
        "activated",  # claps detected, session starting
        "listening",
        "transcribing",
        "thinking",
        "speaking",
        "ended",  # session closed, back to idle soon
    }
)

_MAX_TEXT = 4000
_QUEUE_SIZE = 256


class VoiceEventIn(BaseModel):
    """Event posted by the voice loop."""

    type: VoiceEventType
    data: Dict[str, Any] = Field(default_factory=dict)


def _sanitize(event_type: str, data: Dict[str, Any]) -> Dict[str, Any] | None:
    """Keep only the fields the HUD understands, bounded in size."""
    if event_type == "state":
        state = str(data.get("state", ""))
        if state not in VOICE_STATES:
            return None
        out: Dict[str, Any] = {"state": state}
        if data.get("reason"):
            out["reason"] = str(data["reason"])[:200]
        return out
    if event_type in ("transcript", "response"):
        return {"text": str(data.get("text", ""))[:_MAX_TEXT]}
    if event_type == "level":
        try:
            level = float(data.get("level", 0.0))
        except (TypeError, ValueError):
            return None
        source = "speaking" if data.get("source") == "speaking" else "listening"
        return {"level": max(0.0, min(1.0, level)), "source": source}
    if event_type == "tool":
        return {
            "name": str(data.get("name", ""))[:100],
            "phase": "end" if data.get("phase") == "end" else "start",
        }
    if event_type == "session":
        return {k: str(v)[:200] for k, v in data.items() if k in ("engine", "model")}
    return None


class VoiceEventHub:
    """Fan-out of voice events to WebSocket clients, plus the latest state.

    Each client queue is paired with the loop that owns it, and delivery goes
    through ``call_soon_threadsafe`` so publishing is safe from any thread or
    event loop (same approach as ``ws_bridge``).
    """

    def __init__(self) -> None:
        self._clients: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._last_state: Optional[Dict[str, Any]] = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_state

    def publish(
        self, event_type: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        clean = _sanitize(event_type, data)
        if clean is None:
            return None
        payload = {"type": event_type, "timestamp": time.time(), "data": clean}
        if event_type == "state":
            self._last_state = payload
        for queue, loop in list(self._clients.items()):
            try:
                loop.call_soon_threadsafe(self._offer, queue, payload)
            except RuntimeError:
                self._clients.pop(queue, None)  # loop closed
        return payload

    @staticmethod
    def _offer(queue: asyncio.Queue, payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # slow client: drop rather than block the publisher

    def add(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._clients[queue] = asyncio.get_running_loop()
        return queue

    def remove(self, queue: asyncio.Queue) -> None:
        self._clients.pop(queue, None)


def create_voice_events_router(hub: Optional[VoiceEventHub] = None) -> APIRouter:
    """Build the ``/v1/voice/events`` (POST) + ``/v1/voice/ws`` (WS) router."""
    voice_hub = hub or VoiceEventHub()
    router = APIRouter(tags=["voice"])

    @router.post("/v1/voice/events")
    async def post_voice_event(event: VoiceEventIn) -> Dict[str, Any]:
        payload = voice_hub.publish(event.type, event.data)
        return {"accepted": payload is not None, "clients": voice_hub.client_count}

    @router.websocket("/v1/voice/ws")
    async def voice_ws(websocket: WebSocket) -> None:
        from openjarvis.server.auth_middleware import authenticate_websocket

        expected_key = getattr(websocket.app.state, "api_key", "")
        authorized, subprotocol = authenticate_websocket(websocket, expected_key)
        if not authorized:
            await websocket.close(code=1008)
            return
        await websocket.accept(subprotocol=subprotocol)
        queue = voice_hub.add()
        recv: asyncio.Task | None = None
        sender: asyncio.Task | None = None
        try:
            snapshot = voice_hub.snapshot()
            if snapshot is not None:
                await websocket.send_json(snapshot)
            recv = asyncio.create_task(websocket.receive())
            sender = asyncio.create_task(queue.get())
            while True:
                done, _ = await asyncio.wait(
                    {recv, sender}, return_when=asyncio.FIRST_COMPLETED
                )
                if recv in done:
                    message = recv.result()
                    if message.get("type") == "websocket.disconnect":
                        break
                    recv = asyncio.create_task(websocket.receive())
                if sender in done:
                    await websocket.send_json(sender.result())
                    sender = asyncio.create_task(queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            voice_hub.remove(queue)
            for task in (recv, sender):
                if task is not None:
                    task.cancel()

    router.voice_hub = voice_hub  # type: ignore[attr-defined]
    return router


__all__ = ["VOICE_STATES", "VoiceEventHub", "create_voice_events_router"]
