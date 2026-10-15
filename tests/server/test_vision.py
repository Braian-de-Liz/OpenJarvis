"""Tests for the HUD screen-reading endpoint (capture + OCR injected)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server import vision
from openjarvis.server.vision import create_vision_router


def _client(*, ocr=None, capture=None, api_key="", client=("127.0.0.1", 50000)):  # noqa: ANN001
    app = FastAPI()
    app.state.api_key = api_key
    app.include_router(
        create_vision_router(
            capture=capture or (lambda monitor: (b"png", 1600, 900)),
            ocr=ocr or (lambda png: ("Olá\nMundo", "pt-BR")),
        )
    )
    return TestClient(app, client=client)


def test_returns_ocr_text_and_metadata():
    res = _client().post("/api/vision/screen")
    assert res.status_code == 200
    assert res.json() == {
        "text": "Olá\nMundo",
        "truncated": False,
        "chars": 9,
        "language": "pt-BR",
        "width": 1600,
        "height": 900,
        "engine": "windows-ocr",
    }


def test_truncates_very_long_screens():
    long_text = "x" * (vision.MAX_CHARS + 50)
    body = (
        _client(ocr=lambda png: (long_text, "pt-BR")).post("/api/vision/screen").json()
    )
    assert body["truncated"] is True
    assert body["chars"] == vision.MAX_CHARS + 50
    assert len(body["text"]) == vision.MAX_CHARS


def test_refuses_remote_callers_without_api_key():
    res = _client(client=("192.168.0.20", 50000)).post("/api/vision/screen")
    assert res.status_code == 403


def test_allows_remote_callers_when_an_api_key_is_configured():
    # The API-key middleware (not mounted here) authenticates them upstream.
    res = _client(client=("192.168.0.20", 50000), api_key="k").post(
        "/api/vision/screen"
    )
    assert res.status_code == 200


def test_missing_dependencies_point_to_the_extra():
    def no_mss(monitor):  # noqa: ANN001
        raise ImportError("No module named 'mss'")

    res = _client(capture=no_mss).post("/api/vision/screen")
    assert res.status_code == 501
    assert "uv sync --extra screen" in res.json()["detail"]


def test_ocr_errors_are_reported():
    def broken(png):  # noqa: ANN001
        raise RuntimeError("Nenhum idioma de OCR instalado")

    res = _client(ocr=broken).post("/api/vision/screen")
    assert res.status_code == 500
    assert "idioma" in res.json()["detail"]
