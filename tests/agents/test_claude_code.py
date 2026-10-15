"""Tests for ClaudeCodeAgent."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import openjarvis.agents  # noqa: F401 -- trigger registration
from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.claude_code import (
    _OUTPUT_END,
    _OUTPUT_START,
    _RUNNER_SRC,
    ClaudeCodeAgent,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL_WRAP = "{start}\n{payload}\n{end}"


def _wrap_output(payload: dict) -> str:
    """Wrap a dict in sentinel markers like the runner would."""
    return _SENTINEL_WRAP.format(
        start=_OUTPUT_START,
        payload=json.dumps(payload),
        end=_OUTPUT_END,
    )


def _mock_proc(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["node", "index.mjs"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestClaudeCodeRegistration:
    def test_agent_id(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        assert agent.agent_id == "claude_code"

    def test_accepts_tools_false(self):
        assert ClaudeCodeAgent.accepts_tools is False

    def test_registry_key(self):
        AgentRegistry.register_value("claude_code", ClaudeCodeAgent)
        assert AgentRegistry.contains("claude_code")
        cls = AgentRegistry.get("claude_code")
        assert cls is ClaudeCodeAgent


# ---------------------------------------------------------------------------
# _ensure_runner tests
# ---------------------------------------------------------------------------


class TestEnsureRunner:
    def test_raises_when_node_not_found(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Node.js"):
                agent._ensure_runner()

    def test_bundled_runner_is_runnable(self):
        package = json.loads((_RUNNER_SRC / "package.json").read_text())

        assert package["main"] == "index.mjs"
        assert (_RUNNER_SRC / package["main"]).is_file()
        assert package["dependencies"]["@anthropic-ai/claude-agent-sdk"] == "0.3.237"
        assert "@anthropic-ai/claude-code" not in package["dependencies"]

    def test_creates_runner_dir(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        # _ensure_runner() resolves its destination via get_config_dir(),
        # which checks $OPENJARVIS_HOME before ever falling back to
        # Path.home() -- so that's the env var to control here, not a
        # Path.home() patch (which get_config_dir() never even calls once
        # OPENJARVIS_HOME is set, e.g. by conftest.py's session-wide
        # isolation fixture).
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        def which(executable):
            return f"/usr/bin/{executable}"

        with (
            patch("shutil.which", side_effect=which),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_proc()
            dest = home_dir / "claude_code_runner"
            result = agent._ensure_runner()
            assert result == dest
            assert (dest / "index.mjs").is_file()
            assert (dest / "package.json").is_file()
            assert mock_run.call_args.args[0] == [
                "/usr/bin/npm",
                "install",
                "--omit=dev",
                "--include=optional",
            ]

    def test_skips_npm_install_when_sdk_version_matches(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        dest = home_dir / "claude_code_runner"
        installed = (
            dest
            / "node_modules"
            / "@anthropic-ai"
            / "claude-agent-sdk"
            / "package.json"
        )
        installed.parent.mkdir(parents=True)
        installed.write_text('{"version":"0.3.237"}')
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        with (
            patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
            patch("subprocess.run") as mock_run,
        ):
            agent._ensure_runner()
            mock_run.assert_not_called()

    def test_reinstalls_legacy_cache(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        home_dir = tmp_path / "home"
        old_package = (
            home_dir
            / "claude_code_runner"
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "package.json"
        )
        old_package.parent.mkdir(parents=True)
        old_package.write_text('{"version":"0.2.126"}')
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        with (
            patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"),
            patch("subprocess.run") as mock_run,
        ):
            agent._ensure_runner()

        assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# run() tests
# ---------------------------------------------------------------------------


class TestClaudeCodeRun:
    def _make_agent(self, **kwargs):
        engine = MagicMock()
        engine.engine_id = "mock"
        defaults = {
            "api_key": "test-key",
            "workspace": "/tmp/test",
        }
        defaults.update(kwargs)
        return ClaudeCodeAgent(engine, "test-model", **defaults)

    def test_successful_run(self):
        agent = self._make_agent()
        output = _wrap_output(
            {
                "content": "Hello from Claude Code!",
                "tool_results": [],
                "metadata": {"message_count": 3},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc) as mock_run,
        ):
            result = agent.run("Say hello")

        assert isinstance(result, AgentResult)
        assert result.content == "Hello from Claude Code!"
        assert result.turns == 1
        assert result.tool_results == []
        assert result.metadata["message_count"] == 3
        assert mock_run.call_args.args[0] == ["node", "index.mjs"]

    def test_run_with_tool_results(self):
        agent = self._make_agent()
        output = _wrap_output(
            {
                "content": "I read the file.",
                "tool_results": [
                    {
                        "tool_name": "Read",
                        "content": "file contents",
                        "success": True,
                    },
                ],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Read main.py")

        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_name == "Read"
        assert result.tool_results[0].content == "file contents"
        assert result.tool_results[0].success is True

    def test_stdin_json_payload(self):
        agent = self._make_agent(
            api_key="sk-test",
            workspace="/projects/myapp",
            session_id="sess-123",
            allowed_tools=["Read", "Write"],
            system_prompt="Be helpful.",
            mode="agent",
        )
        output = _wrap_output(
            {
                "content": "ok",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch(
                "subprocess.run",
                return_value=proc,
            ) as mock_run,
        ):
            agent.run("Do something")

        call_kwargs = mock_run.call_args
        stdin_json = json.loads(call_kwargs.kwargs["input"])
        assert stdin_json["prompt"] == "Do something"
        assert "api_key" not in stdin_json
        assert stdin_json["workspace"] == "/projects/myapp"
        assert stdin_json["session_id"] == "sess-123"
        assert stdin_json["allowed_tools"] == ["Read", "Write"]
        assert stdin_json["system_prompt"] == "Be helpful."

    def test_timeout_handling(self):
        agent = self._make_agent(timeout=5)
        exc = subprocess.TimeoutExpired(
            cmd="node",
            timeout=5,
        )

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", side_effect=exc),
        ):
            result = agent.run("Slow task")

        assert "timed out" in result.content
        assert result.metadata["error"] is True
        assert result.metadata["error_type"] == "timeout"

    def test_nonzero_exit_code(self):
        agent = self._make_agent()
        proc = _mock_proc(
            returncode=1,
            stderr="ENOENT: module not found",
        )

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Failing task")

        assert "failed" in result.content.lower()
        assert "ENOENT" in result.content
        assert result.metadata["error"] is True
        assert result.metadata["returncode"] == 1

    def test_no_sentinels_in_output(self):
        """Plain text without sentinels used as content."""
        agent = self._make_agent()
        proc = _mock_proc(stdout="Some plain text output")

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Query")

        assert result.content == "Some plain text output"
        assert result.tool_results == []

    def test_malformed_json_in_sentinels(self):
        """Sentinel-wrapped content is not valid JSON."""
        agent = self._make_agent()
        bad = f"{_OUTPUT_START}\nnot valid json\n{_OUTPUT_END}"
        proc = _mock_proc(stdout=bad)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Query")

        assert result.metadata.get("parse_error") is True


# ---------------------------------------------------------------------------
# Event bus tests
# ---------------------------------------------------------------------------


class TestClaudeCodeEvents:
    def test_emits_turn_start_and_end(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            bus=bus,
            api_key="k",
        )
        output = _wrap_output(
            {
                "content": "hi",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch.object(agent, "_run_streaming", return_value=proc),
        ):
            agent.run("Hello")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in types
        assert EventType.AGENT_TURN_END in types

    def test_turn_start_data(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            bus=bus,
            api_key="k",
        )
        output = _wrap_output(
            {
                "content": "hi",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch.object(agent, "_run_streaming", return_value=proc),
        ):
            agent.run("test input")

        start_events = [
            e for e in bus.history if e.event_type == EventType.AGENT_TURN_START
        ]
        assert len(start_events) == 1
        assert start_events[0].data["agent"] == "claude_code"
        assert start_events[0].data["input"] == "test input"

    def test_error_emits_turn_end(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            bus=bus,
            api_key="k",
        )
        proc = _mock_proc(returncode=1, stderr="error")

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch.object(agent, "_run_streaming", return_value=proc),
        ):
            agent.run("Fail")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_END in types


# ---------------------------------------------------------------------------
# _parse_output unit tests
# ---------------------------------------------------------------------------


class TestParseOutput:
    def test_parses_valid_sentinels(self):
        payload = {
            "content": "hello",
            "tool_results": [],
            "metadata": {"k": "v"},
        }
        stdout = _wrap_output(payload)
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert content == "hello"
        assert tools == []
        assert meta == {"k": "v"}

    def test_no_sentinels(self):
        content, tools, meta = ClaudeCodeAgent._parse_output(
            "plain text",
        )
        assert content == "plain text"
        assert tools == []
        assert meta == {}

    def test_tool_results_parsed(self):
        payload = {
            "content": "done",
            "tool_results": [
                {
                    "tool_name": "Bash",
                    "content": "output",
                    "success": True,
                },
                {
                    "tool_name": "Write",
                    "content": "wrote file",
                    "success": False,
                },
            ],
            "metadata": {},
        }
        stdout = _wrap_output(payload)
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert len(tools) == 2
        assert tools[0].tool_name == "Bash"
        assert tools[0].success is True
        assert tools[1].tool_name == "Write"
        assert tools[1].success is False

    def test_extra_stdout_before_sentinels(self):
        """Runner may log before sentinels -- should parse."""
        payload = {
            "content": "result",
            "tool_results": [],
            "metadata": {},
        }
        stdout = "some debug output\n" + _wrap_output(payload) + "\nmore output"
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert content == "result"

    def test_invalid_json(self):
        stdout = f"{_OUTPUT_START}\n{{broken\n{_OUTPUT_END}"
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert meta.get("parse_error") is True


# ---------------------------------------------------------------------------
# Constructor defaults tests
# ---------------------------------------------------------------------------


class TestClaudeCodeDefaults:
    def test_api_key_is_never_stored_or_sent(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-123")
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model", api_key="explicit-key")
        assert not hasattr(agent, "_api_key")

    def test_default_timeout(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        assert agent._timeout == 300

    def test_custom_timeout(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            timeout=60,
        )
        assert agent._timeout == 60

    def test_no_bus_works(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            api_key="k",
        )
        output = _wrap_output(
            {
                "content": "ok",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Hello")

        assert result.content == "ok"


# ---------------------------------------------------------------------------
# Live streaming + subscription-only guarantees
# ---------------------------------------------------------------------------

_FAKE_RUNNER = """
import json, sys, time
req = json.loads(sys.stdin.read())
P = "---OJ_EVENT--- "
print(P + json.dumps({"type": "text_delta", "text": "Ol"}), flush=True)
print(P + json.dumps({"type": "tool_start", "id": "t1", "tool": "Read",
                      "input": {"file": "a"}}), flush=True)
print(P + json.dumps({"type": "tool_end", "id": "t1", "success": True,
                      "content": "ok"}), flush=True)
print(P + json.dumps({"type": "text_delta", "text": "a"}), flush=True)
print("---OPENJARVIS_OUTPUT_START---")
print(json.dumps({"content": "Ola", "tool_results": [], "metadata": {}}))
print("---OPENJARVIS_OUTPUT_END---")
"""


def _streaming_agent(tmp_path, script, bus, **kwargs):
    import sys

    (tmp_path / "index.mjs").write_text(script, encoding="utf-8")
    engine = MagicMock()
    engine.engine_id = "mock"
    agent = ClaudeCodeAgent(engine, "m", bus=bus, workspace=str(tmp_path), **kwargs)
    agent._node_executable = sys.executable
    return agent


class TestClaudeCodeStreaming:
    def test_publishes_live_events(self, tmp_path):
        bus = EventBus(record_history=True)
        agent = _streaming_agent(tmp_path, _FAKE_RUNNER, bus)
        with patch.object(agent, "_ensure_runner", return_value=tmp_path):
            result = agent.run("hi")

        assert result.content == "Ola"
        by_type = [(e.event_type, e.data) for e in bus.history]
        deltas = [d["text"] for t, d in by_type if t == EventType.AGENT_TEXT_DELTA]
        assert deltas == ["Ol", "a"]
        starts = [
            d for t, d in by_type
            if t == EventType.TOOL_CALL_START and d["tool"] == "Read"
        ]
        ends = [
            d for t, d in by_type
            if t == EventType.TOOL_CALL_END and d["tool"] == "Read"
        ]
        assert starts[0]["arguments"] == {"file": "a"}
        assert ends[0]["success"] is True

    def test_streaming_timeout_kills_runner(self, tmp_path):
        bus = EventBus()
        agent = _streaming_agent(
            tmp_path, "import time\ntime.sleep(30)\n", bus, timeout=1
        )
        with patch.object(agent, "_ensure_runner", return_value=tmp_path):
            result = agent.run("hi")
        assert result.metadata["error_type"] == "timeout"

    def test_streaming_runner_failure(self, tmp_path):
        bus = EventBus()
        agent = _streaming_agent(
            tmp_path, "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n", bus
        )
        with patch.object(agent, "_ensure_runner", return_value=tmp_path):
            result = agent.run("hi")
        assert result.metadata["error"] is True
        assert "boom" in result.content


class TestSubscriptionOnly:
    """The agent must never authenticate with an API key."""

    def test_runner_strips_api_key_env(self):
        from pathlib import Path

        import openjarvis.agents.claude_code as mod

        source = (Path(mod.__file__).parent / "claude_code_runner" / "index.mjs")
        text = source.read_text(encoding="utf-8")
        # The request's api_key must never be copied into the environment.
        assert "request.api_key" not in text.replace("request.api_key is", "")
        assert "process.env.ANTHROPIC_API_KEY =" not in text
        # Env is scrubbed of every credential source, project settings are not
        # loaded, and the run aborts unless the SDK reports the login.
        assert 'key.startsWith("ANTHROPIC_")' in text
        assert 'key.startsWith("CLAUDE_CODE_USE_")' in text
        assert 'settingSources: ["user"]' in text
        assert "apiKeySource" in text


class TestServeRefusesApiKey:
    @pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
    def test_serve_claude_code_refuses_with_anthropic_credential(
        self, monkeypatch, var
    ):
        from click.testing import CliRunner

        from openjarvis.cli.serve import serve

        monkeypatch.setenv(var, "sk-ant-test")
        result = CliRunner().invoke(serve, ["--agent", "claude_code", "--port", "8999"])
        assert result.exit_code == 1
        assert "Refusing to start" in result.output


class TestChatMode:
    def _agent(self, **kwargs):
        engine = MagicMock()
        engine.engine_id = "mock"
        return ClaudeCodeAgent(engine, "m", workspace="/tmp/x", **kwargs)

    def _request_for(self, agent, text, context=None):
        proc = _mock_proc(stdout=_wrap_output({"content": "ok", "tool_results": []}))
        with (
            patch.object(agent, "_ensure_runner", return_value="/fake"),
            patch("subprocess.run", return_value=proc) as run,
        ):
            agent.run(text, context=context)
        return json.loads(run.call_args.kwargs["input"])

    def test_chat_is_the_default_and_drops_tools(self):
        agent = self._agent(allowed_tools=["Read", "Bash"])
        req = self._request_for(agent, "oi")
        assert req["mode"] == "chat"
        assert req["allowed_tools"] == []
        assert "JARVIS" in req["system_prompt"]

    def test_agent_mode_keeps_tools_and_prompt(self):
        agent = self._agent(mode="agent", allowed_tools=["Read"], system_prompt="X")
        req = self._request_for(agent, "oi")
        assert req["mode"] == "agent"
        assert req["allowed_tools"] == ["Read"]
        assert req["system_prompt"] == "X"
        assert req["prompt"] == "oi"

    def test_env_can_select_agent_mode(self, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_CLAUDE_CODE_MODE", "agent")
        assert self._agent()._mode == "agent"

    def test_chat_prefixes_recent_history(self):
        from openjarvis.agents._stubs import AgentContext
        from openjarvis.core.types import Message, Role

        ctx = AgentContext()
        ctx.conversation.add(Message(role=Role.USER, content="meu nome é Braian"))
        ctx.conversation.add(Message(role=Role.ASSISTANT, content="Prazer, Braian."))
        req = self._request_for(self._agent(), "qual meu nome?", ctx)
        assert "Usuário: meu nome é Braian" in req["prompt"]
        assert "JARVIS: Prazer, Braian." in req["prompt"]
        assert req["prompt"].endswith("Usuário: qual meu nome?")

    def test_runner_chat_mode_is_lean(self):
        from pathlib import Path

        import openjarvis.agents.claude_code as mod

        runner = Path(mod.__file__).parent / "claude_code_runner" / "index.mjs"
        text = runner.read_text(encoding="utf-8")
        assert 'request.mode === "chat"' in text
        assert "options.tools = []" in text
        assert "options.settingSources = []" in text


class TestClaudeModelChoice:
    """The HUD picks the Claude model via a suffix: ``claude-code:opus``."""

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("claude-code", ""),
            ("claude-code:opus", "opus"),
            ("claude-code-agent:claude-sonnet-4-5", "claude-sonnet-4-5"),
            ("claude-code:", ""),
            ("claude-code:opus; rm -rf /", ""),  # not a model id
            ("claude-code:" + "x" * 80, ""),
        ],
    )
    def test_claude_model_from(self, model, expected):
        from openjarvis.agents.claude_code import claude_model_from

        assert claude_model_from(model) == expected

    def _request(self, agent_model):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, agent_model)
        proc = _mock_proc(
            stdout=_wrap_output({"content": "ok", "tool_results": [], "metadata": {}})
        )
        with (
            patch.object(agent, "_ensure_runner", return_value="/fake"),
            patch("subprocess.run", return_value=proc) as run,
        ):
            agent.run("oi")
        return json.loads(run.call_args.kwargs["input"])

    def test_suffix_is_sent_as_the_runner_model(self):
        assert self._request("claude-code:opus")["model"] == "opus"

    def test_no_suffix_keeps_the_plan_default(self):
        assert "model" not in self._request("claude-code")

    def test_runner_applies_the_model_and_reports_it(self):
        text = _RUNNER_SRC.joinpath("index.mjs").read_text(encoding="utf-8")
        assert "options.model = request.model" in text
        assert 'emitEvent({ type: "model", model: message.model })' in text

    def test_model_event_is_published(self, tmp_path):
        script = _FAKE_RUNNER.replace(
            'print(P + json.dumps({"type": "text_delta", "text": "Ol"}), flush=True)',
            'print(P + json.dumps({"type": "model", "model": "claude-opus-4-1"}),'
            " flush=True)\n"
            'print(P + json.dumps({"type": "text_delta", "text": "Ol"}), flush=True)',
        )
        bus = EventBus(record_history=True)
        agent = _streaming_agent(tmp_path, script, bus)
        with patch.object(agent, "_ensure_runner", return_value=tmp_path):
            agent.run("hi")
        infos = [
            e.data for e in bus.history if e.event_type == EventType.AGENT_MODEL_INFO
        ]
        assert infos == [{"agent": "claude_code", "model": "claude-opus-4-1"}]

    def test_suffixed_ids_are_never_cloud_models(self):
        from openjarvis.server.cloud_router import is_cloud_model

        assert not is_cloud_model("claude-code:opus")
        assert not is_cloud_model("claude-code-agent:sonnet")
        assert is_cloud_model("claude-sonnet-4-5")  # the paid API model still is
