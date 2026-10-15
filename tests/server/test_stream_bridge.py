"""Regression tests for streaming completed agent responses."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from openjarvis.agents._stubs import AgentResult  # noqa: E402
from openjarvis.core.events import EventBus  # noqa: E402
from openjarvis.core.types import ToolResult  # noqa: E402
from openjarvis.server.models import ChatCompletionRequest  # noqa: E402
from openjarvis.server.stream_bridge import AgentStreamBridge  # noqa: E402


def _streamed_content(events: list[str]) -> str:
    """Join assistant content from OpenAI-compatible data chunks."""
    content = []
    for event in events:
        if not event.startswith("data: {"):
            continue
        payload = json.loads(event.removeprefix("data: ").strip())
        choices = payload.get("choices")
        if choices and choices[0]["delta"].get("content"):
            content.append(choices[0]["delta"]["content"])
    return "".join(content)


def test_stream_replays_grounded_agent_result_without_second_inference():
    grounded_content = "My name is Jarvis. The tool reports 72 degrees."
    agent = MagicMock()
    agent._model = "configured-model"
    agent.run.return_value = AgentResult(
        content=grounded_content,
        tool_results=[
            ToolResult(tool_name="weather", content="72 degrees", success=True)
        ],
        metadata={"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    )

    async def ungrounded_replay(*args, **kwargs):
        raise AssertionError("stream_full must not run after agent.run")
        yield  # pragma: no cover

    agent._engine.stream_full = ungrounded_replay
    request = ChatCompletionRequest(
        model="requested-model",
        messages=[{"role": "user", "content": "Who are you, and what's outside?"}],
        stream=True,
    )
    bridge = AgentStreamBridge(agent, EventBus(), request.model, request)

    async def collect_events() -> list[str]:
        return [event async for event in bridge.stream()]

    events = asyncio.run(collect_events())

    assert _streamed_content(events) == grounded_content
    assert any(event.startswith("event: tool_results\n") for event in events)
    agent.run.assert_called_once()
    assert agent._model == "configured-model"


def test_tool_call_start_serializes_arguments_for_sse_without_mutating_event():
    bridge = object.__new__(AgentStreamBridge)
    event_data = {
        "tool": "web_search",
        "arguments": {"query": "python"},
        "agent": "agent-1",
    }

    event = bridge._format_named_event("tool_call_start", event_data)
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["arguments"] == '{"query": "python"}'
    assert event_data["arguments"] == {"query": "python"}


def test_tool_call_start_preserves_already_serialized_arguments():
    bridge = object.__new__(AgentStreamBridge)

    event = bridge._format_named_event(
        "tool_call_start",
        {"tool": "web_search", "arguments": '{"query":"python"}'},
    )
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["arguments"] == '{"query":"python"}'


def test_stream_forwards_text_deltas_live_and_skips_replay():
    from openjarvis.core.events import EventType

    bus = EventBus()
    agent = MagicMock()
    agent._model = "m"

    def run(*args, **kwargs):
        bus.publish(EventType.AGENT_TEXT_DELTA, {"text": "Ol"})
        bus.publish(EventType.AGENT_TEXT_DELTA, {"text": "a!"})
        return AgentResult(content="Ola!", tool_results=[], metadata={})

    agent.run.side_effect = run
    request = ChatCompletionRequest(
        model="claude-code",
        messages=[{"role": "user", "content": "oi"}],
        stream=True,
    )
    bridge = AgentStreamBridge(agent, bus, request.model, request)

    async def collect_events() -> list[str]:
        return [event async for event in bridge.stream()]

    events = asyncio.run(collect_events())

    # Streamed once (not replayed a second time from the final result).
    assert _streamed_content(events) == "Ola!"


def test_claude_code_never_routes_to_cloud_with_api_key(monkeypatch):
    """stream:true + model claude-code must use the agent, never the cloud router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.core.events import EventType
    from openjarvis.server import cloud_router
    from openjarvis.server.routes import router

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    async def boom(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("cloud router used for claude_code")
        yield

    monkeypatch.setattr(cloud_router, "stream_cloud", boom)

    bus = EventBus()
    agent = MagicMock()
    agent.agent_id = "claude_code"
    agent._model = "claude-sonnet-4-5"
    agent._tools = None

    def run(*args, **kwargs):
        bus.publish(EventType.AGENT_TEXT_DELTA, {"agent": "claude_code", "text": "Ol"})
        bus.publish(EventType.AGENT_TEXT_DELTA, {"agent": "claude_code", "text": "a"})
        return AgentResult(content="Ola", tool_results=[], metadata={})

    agent.run.side_effect = run
    app = FastAPI()
    app.include_router(router)
    app.state.engine = MagicMock()
    app.state.agent = agent
    app.state.bus = bus
    app.state.model = "claude-sonnet-4-5"

    client = TestClient(app)
    body = {
        "model": "claude-sonnet-4-5",
        "messages": [{"role": "user", "content": "oi"}],
        "stream": True,
    }
    for extra in ({}, {"tools": [{"type": "function", "function": {"name": "x"}}]}):
        with client.stream("POST", "/v1/chat/completions", json={**body, **extra}) as r:
            events = [line + "\n\n" for line in r.iter_lines() if line]
        assert _streamed_content(events) == "Ola"
    agent.run.assert_called()
    assert cloud_router.is_cloud_model("claude-code") is False


def test_cloud_keys_file_ignored_in_claude_code_mode(monkeypatch, tmp_path):
    from openjarvis.server import cloud_router

    keys_file = tmp_path / "cloud-keys.env"
    keys_file.write_text("ANTHROPIC_API_KEY=sk-from-file\n")
    monkeypatch.setattr(cloud_router, "_CLOUD_ENV_FILE", keys_file)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    assert cloud_router._load_keys()["ANTHROPIC_API_KEY"]
    monkeypatch.setenv("OPENJARVIS_NO_ANTHROPIC_API", "1")
    assert "ANTHROPIC_API_KEY" not in cloud_router._load_keys()


def _plain_server(monkeypatch):
    """A server started WITHOUT --agent claude_code (e.g. plain Ollama)."""
    from fastapi import FastAPI

    from openjarvis.core.events import EventType
    from openjarvis.server.routes import router

    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    bus = EventBus()
    created = []

    class FakeClaudeCode:
        agent_id = "claude_code"
        _tools = None

        def __init__(self, engine, model, **kwargs):
            self._model = model
            self.mode = kwargs.get("mode")
            created.append(self)

        def run(self, text, context=None, **kwargs):
            bus.publish(
                EventType.AGENT_TEXT_DELTA, {"agent": "claude_code", "text": "claude"}
            )
            return AgentResult(content="claude", tool_results=[], metadata={})

    monkeypatch.setattr(
        "openjarvis.agents.claude_code.ClaudeCodeAgent", FakeClaudeCode
    )
    engine = MagicMock()
    engine.list_models.return_value = ["llama3"]
    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    app.state.agent = None
    app.state.bus = bus
    app.state.model = "llama3"
    return app, created


def test_hud_can_switch_to_claude_code_on_a_plain_server(monkeypatch):
    from fastapi.testclient import TestClient

    app, created = _plain_server(monkeypatch)
    client = TestClient(app)
    models = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert "llama3" in models
    assert "claude-code" in models and "claude-code-agent" in models

    body = {
        "model": "claude-code",
        "messages": [{"role": "user", "content": "oi"}],
        "stream": True,
    }
    with client.stream("POST", "/v1/chat/completions", json=body) as r:
        events = [line + "\n\n" for line in r.iter_lines() if line]
    assert _streamed_content(events) == "claude"
    assert len(created) == 1  # agent built lazily, then reused


@pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_claude_code_option_refused_while_api_key_is_set(monkeypatch, var):
    from fastapi.testclient import TestClient

    app, created = _plain_server(monkeypatch)
    monkeypatch.setenv(var, "sk-ant-test")
    client = TestClient(app)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "claude-code",
            "messages": [{"role": "user", "content": "oi"}],
        },
    )
    assert r.status_code == 409
    assert var in r.json()["detail"]
    assert created == []  # the agent was never even created


def test_conversation_and_agent_modes_get_separate_agents(monkeypatch):
    from fastapi.testclient import TestClient

    app, created = _plain_server(monkeypatch)
    client = TestClient(app)
    for model in ("claude-code", "claude-code-agent", "claude-code"):
        r = client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "oi"}]},
        )
        assert r.status_code == 200
    assert sorted(a.mode for a in created) == ["agent", "chat"]  # reused per mode


def test_agent_model_is_also_refused_while_api_key_is_set(monkeypatch):
    from fastapi.testclient import TestClient

    app, created = _plain_server(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    r = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "claude-code-agent",
            "messages": [{"role": "user", "content": "oi"}],
        },
    )
    assert r.status_code == 409 and created == []
