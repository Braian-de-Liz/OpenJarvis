"""Tests for the HUD reminders router (server-owned scheduler)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.reminders import create_reminders_router
from openjarvis.server.voice_events import VoiceEventHub


class _RecordingHub(VoiceEventHub):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type, data):  # noqa: ANN001
        self.events.append((event_type, data))
        return super().publish(event_type, data)


@pytest.fixture()
def setup(tmp_path):
    hub = _RecordingHub()
    router = create_reminders_router(
        hub, db_path=tmp_path / "reminders.db", start=False
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), router, hub


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_create_in_minutes_and_list(setup):
    client, _, _ = setup
    res = client.post("/v1/reminders", json={"text": "Beber água", "in_minutes": 30})
    assert res.status_code == 201
    body = res.json()
    assert body["text"] == "Beber água"
    assert body["status"] == "active"
    due = datetime.fromisoformat(body["next_run"])
    delta = due - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < delta <= timedelta(minutes=30)

    listed = client.get("/v1/reminders").json()
    assert [r["text"] for r in listed] == ["Beber água"]


def test_create_at_accepts_z_suffix(setup):
    client, _, _ = setup
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    res = client.post(
        "/v1/reminders",
        json={"text": "Reunião", "at": when.strftime("%Y-%m-%dT%H:%M:%SZ")},
    )
    assert res.status_code == 201
    assert datetime.fromisoformat(res.json()["next_run"]) == when


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "x"},  # neither
        {"text": "x", "in_minutes": 5, "at": "2099-01-01T00:00:00Z"},  # both
        {"text": "x", "at": "2000-01-01T00:00:00Z"},  # past
        {"text": "x", "at": "2099-01-01T00:00:00"},  # no timezone
        {"text": "   ", "in_minutes": 5},  # blank
        {"text": "x", "in_minutes": -1},
    ],
)
def test_rejects_invalid_reminders(setup, payload):
    client, _, _ = setup
    assert client.post("/v1/reminders", json=payload).status_code == 422


def test_due_reminder_is_announced_and_leaves_the_list(setup):
    client, router, hub = setup
    rid = client.post(
        "/v1/reminders", json={"text": "Alongar", "in_minutes": 1}
    ).json()["id"]
    store = router.reminder_store
    task = store.get_task(rid)
    task["next_run"] = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))
    store.update_task(task)

    for due in store.get_due_tasks(datetime.now(timezone.utc).isoformat()):
        from openjarvis.scheduler.scheduler import ScheduledTask

        router.reminder_scheduler._execute_task(ScheduledTask.from_dict(due))

    assert (
        "notify",
        {"kind": "reminder", "title": "Lembrete", "text": "Alongar"},
    ) in hub.events
    assert client.get("/v1/reminders").json() == []  # once → done


def test_repeating_reminder_keeps_first_time_and_interval(setup):
    client, _, _ = setup
    body = client.post(
        "/v1/reminders", json={"text": "Postura", "in_minutes": 10, "every_minutes": 60}
    ).json()
    assert body["every_minutes"] == 60
    delta = datetime.fromisoformat(body["next_run"]) - datetime.now(timezone.utc)
    assert timedelta(minutes=9) < delta <= timedelta(minutes=10)


def test_pause_resume_delete(setup):
    client, _, _ = setup
    rid = client.post(
        "/v1/reminders", json={"text": "Pausável", "in_minutes": 5}
    ).json()["id"]
    assert client.post(f"/v1/reminders/{rid}/pause").json()["status"] == "paused"
    assert client.post(f"/v1/reminders/{rid}/resume").json()["status"] == "active"
    assert client.delete(f"/v1/reminders/{rid}").status_code == 200
    assert client.get("/v1/reminders").json() == []
    assert client.delete(f"/v1/reminders/{rid}").status_code == 404


def test_only_reminders_are_visible(setup):
    client, router, _ = setup
    router.reminder_scheduler.create_task(
        "agent prompt", "once", "2099-01-01T00:00:00+00:00"
    )
    assert client.get("/v1/reminders").json() == []
