"""Tests for token usage on direct streams and the context-window route."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.core.types import Message, Role
from openjarvis.server.context_window import (
    CLAUDE_WINDOW,
    create_context_window_router,
    describe_window,
)
from openjarvis.server.token_usage import (
    snapshot,
    stream_usage,
    stream_usage_owner,
)

# --- context window --------------------------------------------------------


def test_local_window_is_num_ctx_capped_by_the_model():
    assert describe_window(
        "llama3.2:1b", show=lambda m: 131072, num_ctx=lambda: 16384
    ) == {
        "model": "llama3.2:1b",
        "window": 16384,
        "model_max": 131072,
        "source": "ollama num_ctx",
        "history_limit": None,
    }
    small = describe_window("tiny", show=lambda m: 2048, num_ctx=lambda: 16384)
    assert small["window"] == 2048


def test_unknown_model_reports_the_requested_num_ctx():
    def boom(model):  # noqa: ANN001
        raise RuntimeError("ollama down")

    out = describe_window("mystery", show=boom, num_ctx=lambda: 8192)
    assert out["window"] == 8192
    assert out["model_max"] is None


def test_claude_code_windows_and_history_limit():
    chat = describe_window("claude-code:opus", show=lambda m: 1, num_ctx=lambda: 1)
    assert chat["window"] == CLAUDE_WINDOW
    assert chat["history_limit"] == {"messages": 12, "chars": 6000}
    agent = describe_window("claude-code-agent", show=lambda m: 1, num_ctx=lambda: 1)
    assert agent["history_limit"] is None


def test_route_caches_ollama_lookups():
    calls = []

    def show(model):  # noqa: ANN001
        calls.append(model)
        return 4096

    app = FastAPI()
    app.include_router(create_context_window_router(show=show, num_ctx=lambda: 16384))
    client = TestClient(app)
    for _ in range(3):
        assert client.get("/api/context-window?model=m").json()["window"] == 4096
    assert calls == ["m"]
    assert client.get("/api/context-window").status_code == 422


# --- stream usage ----------------------------------------------------------


class _Ollama:
    def __init__(self):
        self._last_stream_usage = {}


class _Multi:
    def __init__(self, owner):
        self._owner = owner

    def _engine_for(self, model):  # noqa: ANN001
        return self._owner


class _Instrumented:
    def __init__(self, inner):
        self._inner = inner


def test_owner_is_found_through_wrappers():
    owner = _Ollama()
    assert stream_usage_owner(_Instrumented(_Multi(owner)), "m") is owner
    assert stream_usage_owner(object(), "m") is None


def test_reports_the_engine_count_recorded_during_this_stream():
    owner = _Ollama()
    before = snapshot(owner)
    owner._last_stream_usage = {"prompt_tokens": 120, "completion_tokens": 30}
    assert stream_usage(owner, before, [], "x") == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
    }


def test_estimates_when_the_engine_recorded_nothing_new():
    owner = _Ollama()
    owner._last_stream_usage = {"prompt_tokens": 999, "completion_tokens": 9}
    before = snapshot(owner)  # stale record from a previous request
    msgs = [Message(role=Role.USER, content="a" * 400)]
    usage = stream_usage(owner, before, msgs, "b" * 80)
    assert usage["estimated"] is True
    assert usage["completion_tokens"] == 20
    assert usage["prompt_tokens"] >= 100
    assert usage["total_tokens"] == usage["prompt_tokens"] + 20


# --- internal operations hidden from the tool stream -------------------------


def test_permission_gates_are_not_reported_as_tools():
    from openjarvis.server.routes import is_internal_operation

    assert is_internal_operation("agent_run")
    assert is_internal_operation("hybrid_agent_run")
    assert not is_internal_operation("Read")
    assert not is_internal_operation("shell_exec")
    assert not is_internal_operation(None)
