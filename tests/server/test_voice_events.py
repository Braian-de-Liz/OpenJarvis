"""Tests for the voice session relay (POST /v1/voice/events → WS /v1/voice/ws)."""

from __future__ import annotations

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


@pytest.fixture
def app():
    from openjarvis.server.voice_events import create_voice_events_router

    app = FastAPI()
    app.include_router(create_voice_events_router())
    return app


def test_post_is_relayed_to_websocket(app):
    client = TestClient(app)
    with client.websocket_connect("/v1/voice/ws") as ws:
        r = client.post(
            "/v1/voice/events", json={"type": "state", "data": {"state": "listening"}}
        )
        assert r.status_code == 200
        assert r.json() == {"accepted": True, "clients": 1}
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["data"] == {"state": "listening"}
        assert isinstance(msg["timestamp"], float)

        client.post(
            "/v1/voice/events",
            json={"type": "transcript", "data": {"text": "abre o spotify"}},
        )
        assert ws.receive_json()["data"] == {"text": "abre o spotify"}


def test_last_state_replayed_on_connect(app):
    client = TestClient(app)
    client.post(
        "/v1/voice/events", json={"type": "state", "data": {"state": "speaking"}}
    )
    with client.websocket_connect("/v1/voice/ws") as ws:
        assert ws.receive_json()["data"]["state"] == "speaking"


def test_invalid_state_rejected_and_level_clamped(app):
    client = TestClient(app)
    r = client.post(
        "/v1/voice/events", json={"type": "state", "data": {"state": "hacked"}}
    )
    assert r.json()["accepted"] is False
    r = client.post("/v1/voice/events", json={"type": "bogus", "data": {}})
    assert r.status_code == 422
    with client.websocket_connect("/v1/voice/ws") as ws:
        client.post(
            "/v1/voice/events",
            json={"type": "level", "data": {"level": 7, "source": "x"}},
        )
        assert ws.receive_json()["data"] == {"level": 1.0, "source": "listening"}


def test_text_is_truncated(app):
    client = TestClient(app)
    with client.websocket_connect("/v1/voice/ws") as ws:
        client.post(
            "/v1/voice/events", json={"type": "response", "data": {"text": "a" * 10000}}
        )
        assert len(ws.receive_json()["data"]["text"]) == 4000


def test_auth_enforced_when_api_key_set():
    from openjarvis.server.auth_middleware import AuthMiddleware
    from openjarvis.server.voice_events import create_voice_events_router

    app = FastAPI()
    app.state.api_key = "secret"
    app.add_middleware(AuthMiddleware, api_key="secret")
    app.include_router(create_voice_events_router())
    client = TestClient(app)

    body = {"type": "state", "data": {"state": "idle"}}
    assert client.post("/v1/voice/events", json=body).status_code == 401
    ok = client.post(
        "/v1/voice/events", json=body, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 200

    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/voice/ws") as ws:
            ws.receive_json()
    with client.websocket_connect(
        "/v1/voice/ws", headers={"Authorization": "Bearer secret"}
    ) as ws:
        assert ws.receive_json()["data"]["state"] == "idle"


def test_registered_in_include_all_routes():
    from openjarvis.server.api_routes import include_all_routes

    app = FastAPI()
    include_all_routes(app)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/v1/voice/events" in paths
    assert "/v1/voice/ws" in paths
