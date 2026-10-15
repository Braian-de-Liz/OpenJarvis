"""HUD reminders: "me lembre às 15h de…" that actually fire while serving.

``jarvis serve`` does not run the prompt ``TaskScheduler`` (that is the job of
``jarvis scheduler start``), so a reminder created there would never fire.
This module gives the server its own ``TaskScheduler`` over a *separate*
store (``reminders.db``), so it never executes or consumes the daemon's tasks.

Reminders need no LLM: when one is due, the scheduler runs it without a
system (dry run) and the end event is turned into a ``notify`` voice event,
which the HUD shows, logs and can read aloud.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openjarvis.scheduler.scheduler import SCHEDULER_TASK_END, TaskScheduler
from openjarvis.scheduler.store import SchedulerStore

logger = logging.getLogger(__name__)

REMINDER_KIND = "reminder"
_POLL_SECONDS = 15
_MAX_TEXT = 300


class ReminderIn(BaseModel):
    """A reminder to create. Exactly one of ``at`` / ``in_minutes`` is required."""

    text: str = Field(min_length=1, max_length=_MAX_TEXT)
    at: Optional[str] = None  # ISO 8601 datetime (with offset or Z)
    in_minutes: Optional[float] = Field(default=None, gt=0, le=60 * 24 * 365)
    every_minutes: Optional[float] = Field(default=None, ge=1, le=60 * 24 * 31)


def _parse_when(at: str) -> datetime:
    """Parse an ISO datetime (accepting a trailing Z on Python 3.10)."""
    raw = at.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError("datetime must include a timezone offset")
    return dt.astimezone(timezone.utc)


def _first_run(body: ReminderIn, now: datetime) -> datetime:
    if (body.at is None) == (body.in_minutes is None):
        raise ValueError("send exactly one of 'at' or 'in_minutes'")
    if body.in_minutes is not None:
        return now + timedelta(minutes=body.in_minutes)
    when = _parse_when(body.at or "")
    if when <= now:
        raise ValueError("'at' must be in the future")
    return when


class _NotifyBus:
    """Minimal bus for the reminder scheduler: END events become HUD notices."""

    def __init__(self, store: SchedulerStore, hub: Any) -> None:
        self._store = store
        self._hub = hub

    def publish(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        if event_type != SCHEDULER_TASK_END or self._hub is None:
            return
        task = self._store.get_task(str((data or {}).get("task_id", "")))
        if not task:
            return
        self._hub.publish(
            "notify",
            {"kind": REMINDER_KIND, "title": "Lembrete", "text": task["prompt"]},
        )


def _view(task: Dict[str, Any]) -> Dict[str, Any]:
    every = None
    if task["schedule_type"] == "interval":
        every = float(task["schedule_value"]) / 60
    return {
        "id": task["id"],
        "text": task["prompt"],
        "status": task["status"],
        "next_run": task.get("next_run"),
        "last_run": task.get("last_run"),
        "every_minutes": every,
    }


def default_reminders_db() -> Path:
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    return Path(DEFAULT_CONFIG_DIR) / "reminders.db"


def create_reminders_router(
    hub: Any = None,
    *,
    db_path: Optional[str | Path] = None,
    start: bool = True,
    poll_seconds: int = _POLL_SECONDS,
) -> APIRouter:
    """Build ``/v1/reminders`` backed by a server-owned scheduler.

    ``hub`` is the voice ``VoiceEventHub`` used to announce reminders.
    Tests pass ``start=False`` and drive ``router.reminder_scheduler`` directly.
    """
    path = Path(db_path) if db_path else default_reminders_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = SchedulerStore(path)
    scheduler = TaskScheduler(
        store, poll_interval=poll_seconds, bus=_NotifyBus(store, hub)
    )
    if start:
        scheduler.start()

    router = APIRouter(prefix="/v1/reminders", tags=["reminders"])

    def _get(reminder_id: str) -> Dict[str, Any]:
        task = store.get_task(reminder_id)
        if not task or (task.get("metadata") or {}).get("kind") != REMINDER_KIND:
            raise HTTPException(status_code=404, detail="Reminder not found")
        return task

    @router.get("")
    def list_reminders() -> List[Dict[str, Any]]:
        tasks = [
            t
            for t in store.list_tasks()
            if (t.get("metadata") or {}).get("kind") == REMINDER_KIND
            and t["status"] in ("active", "paused")
        ]
        tasks.sort(key=lambda t: t.get("next_run") or "~")
        return [_view(t) for t in tasks]

    @router.post("", status_code=201)
    def create_reminder(body: ReminderIn) -> Dict[str, Any]:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="text is empty")
        now = datetime.now(timezone.utc)
        try:
            first = _first_run(body, now)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        metadata = {"kind": REMINDER_KIND}
        if body.every_minutes:
            task = scheduler.create_task(
                text, "interval", str(body.every_minutes * 60), metadata=metadata
            )
            # First ring at the requested time, then every N minutes.
            data = store.get_task(task.id) or task.to_dict()
            data["next_run"] = first.isoformat()
            store.update_task(data)
        else:
            task = scheduler.create_task(
                text, "once", first.isoformat(), metadata=metadata
            )
        return _view(store.get_task(task.id) or task.to_dict())

    @router.post("/{reminder_id}/pause")
    def pause_reminder(reminder_id: str) -> Dict[str, Any]:
        _get(reminder_id)
        scheduler.pause_task(reminder_id)
        return _view(_get(reminder_id))

    @router.post("/{reminder_id}/resume")
    def resume_reminder(reminder_id: str) -> Dict[str, Any]:
        _get(reminder_id)
        scheduler.resume_task(reminder_id)
        return _view(_get(reminder_id))

    @router.delete("/{reminder_id}")
    def delete_reminder(reminder_id: str) -> Dict[str, str]:
        _get(reminder_id)
        store.delete_task(reminder_id)
        return {"status": "deleted"}

    router.reminder_scheduler = scheduler  # type: ignore[attr-defined]
    router.reminder_store = store  # type: ignore[attr-defined]
    return router


__all__ = [
    "REMINDER_KIND",
    "ReminderIn",
    "create_reminders_router",
    "default_reminders_db",
]
