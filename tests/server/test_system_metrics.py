"""Tests for the /api/system/metrics HUD telemetry route."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.system_metrics import create_system_metrics_router


class FakePsutil:
    """Deterministic psutil stand-in; each net read adds the given deltas."""

    def __init__(self, sent_step: int = 1_000_000, recv_step: int = 2_000_000):
        self.sent = 0
        self.recv = 0
        self.sent_step = sent_step
        self.recv_step = recv_step

    def cpu_percent(self, interval=None):
        return 12.5

    def virtual_memory(self):
        return SimpleNamespace(percent=40.0)

    def net_io_counters(self):
        self.sent += self.sent_step
        self.recv += self.recv_step
        return SimpleNamespace(bytes_sent=self.sent, bytes_recv=self.recv)


def _client(**kwargs) -> TestClient:
    app = FastAPI()
    app.include_router(create_system_metrics_router(**kwargs))
    return TestClient(app)


def test_returns_json_with_all_keys():
    client = _client(
        psutil_module=FakePsutil(),
        gpu_reader=lambda: {"gpu": 33.0, "temp": 61.0},
    )
    res = client.get("/api/system/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    body = res.json()
    assert set(body) == {"cpu", "ram", "gpu", "temp", "netUp", "netDown"}
    assert body["cpu"] == 12.5
    assert body["ram"] == 40.0
    assert body["gpu"] == 33.0
    assert body["temp"] == 61.0
    assert body["netUp"] > 0
    assert body["netDown"] > body["netUp"]


def test_network_never_negative_after_counter_reset():
    ps = FakePsutil()
    client = _client(psutil_module=ps, gpu_reader=lambda: None)
    client.get("/api/system/metrics")
    # Simulate an adapter reset: counters go backwards.
    ps.sent, ps.recv = -10_000_000, -10_000_000
    body = client.get("/api/system/metrics").json()
    assert body["netUp"] >= 0
    assert body["netDown"] >= 0


def test_gpu_fields_null_without_nvml():
    client = _client(psutil_module=FakePsutil(), gpu_reader=lambda: None)
    body = client.get("/api/system/metrics").json()
    assert body["gpu"] is None
    assert body["temp"] is None


def test_gpu_reader_errors_are_swallowed():
    def boom():
        raise RuntimeError("nvml exploded")

    client = _client(psutil_module=FakePsutil(), gpu_reader=boom)
    res = client.get("/api/system/metrics")
    assert res.status_code == 200
    assert res.json()["gpu"] is None


def test_503_without_psutil(monkeypatch: pytest.MonkeyPatch):
    import openjarvis.server.system_metrics as mod

    monkeypatch.setattr(mod, "_load_psutil", lambda: None)
    client = _client(gpu_reader=lambda: None)
    res = client.get("/api/system/metrics")
    assert res.status_code == 503
