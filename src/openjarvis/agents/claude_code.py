"""ClaudeCodeAgent -- wraps the Claude Agent SDK via Node.js subprocess bridge.

Spawns a Node.js runner process that calls the
``@anthropic-ai/claude-agent-sdk`` package, communicating via JSON over
stdin/stdout with sentinel-delimited output.

The engine parameter is accepted for interface conformance with BaseAgent but
is not used -- inference is handled entirely by the Claude Agent SDK.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

# Sentinel markers for parsing subprocess output
_OUTPUT_START = "---OPENJARVIS_OUTPUT_START---"
_OUTPUT_END = "---OPENJARVIS_OUTPUT_END---"
# Conversation mode (default): no tools and a short prompt, so each message
# costs a few hundred tokens instead of ~22k of fixed Claude Code context.
_CHAT_SYSTEM_PROMPT = (
    "Você é o JARVIS, um assistente pessoal. Responda em português do Brasil, "
    "de forma curta, clara e direta."
)
_HISTORY_MESSAGES = 12
_HISTORY_MAX_CHARS = 6000

# Live events emitted by the runner, one JSON object per line.
_EVENT_PREFIX = "---OJ_EVENT--- "

# Path to the bundled runner source (relative to this module).
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_RUNNER_SRC = Path(__file__).resolve().parent / "claude_code_runner"
if not _RUNNER_SRC.exists():
    _RUNNER_SRC = (
        Path(__file__).resolve().parents[2] / "_node_modules" / "claude_code_runner"
    )


def _kill_process_tree(proc: "subprocess.Popen[str]") -> None:
    """Kill the runner and the ``claude`` process it spawned."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    try:
        proc.kill()
    except OSError:
        pass


@AgentRegistry.register("claude_code")
class ClaudeCodeAgent(BaseAgent):
    """Agent that wraps the Claude Agent SDK via a Node.js subprocess.

    Spawns a Node.js process running ``index.mjs`` which imports
    ``@anthropic-ai/claude-agent-sdk`` and streams agentic responses.  Results
    are communicated back via sentinel-delimited JSON on stdout.

    The ``engine`` parameter is accepted for BaseAgent interface conformance
    but is not used -- all inference is handled by the Claude Agent SDK.
    """

    agent_id = "claude_code"
    accepts_tools = False
    required_capabilities = ("code:execute", "file:read", "file:write")
    _default_temperature = 0.7
    _default_max_tokens = 1024

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: str = "",
        workspace: str = "",
        session_id: str = "",
        allowed_tools: Optional[List[str]] = None,
        system_prompt: str = "",
        mode: Optional[str] = None,
        timeout: int = 300,
        capability_policy: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            capability_policy=capability_policy,
            rate_limiter=rate_limiter,
            agent_id=agent_id,
        )
        # API keys are never used: auth is the local Claude Code login only.
        # ``api_key`` is accepted for backward compatibility and ignored.
        del api_key
        self._workspace = workspace or os.getcwd()
        self._session_id = session_id
        self._allowed_tools = allowed_tools
        self._system_prompt = system_prompt
        # "chat" (default): light conversation, no tools. "agent": full Claude
        # Code with tools (file access, shell). OPENJARVIS_CLAUDE_CODE_MODE
        # overrides the default.
        chosen = mode or os.environ.get("OPENJARVIS_CLAUDE_CODE_MODE", "chat")
        self._mode = "agent" if chosen == "agent" else "chat"
        self._timeout = timeout
        self._node_executable = "node"

    # ------------------------------------------------------------------
    # Runner management
    # ------------------------------------------------------------------

    def _ensure_runner(self) -> Path:
        """Copy the bundled runner to ``~/.openjarvis/claude_code_runner/``
        and install the Agent SDK when it is missing or outdated.

        Returns the path to the runner directory.

        Raises :class:`RuntimeError` if Node.js or npm is not available.
        """
        node_path = shutil.which("node")
        if node_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires Node.js (>=22). "
                "Install it from https://nodejs.org/ or via your package manager."
            )
        npm_path = shutil.which("npm")
        if npm_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires npm. Install Node.js (>=22) with npm."
            )
        self._node_executable = node_path

        dest = get_config_dir() / "claude_code_runner"
        dest.mkdir(parents=True, exist_ok=True)

        for name in ("package.json", "index.mjs"):
            shutil.copy2(_RUNNER_SRC / name, dest / name)

        package = json.loads((dest / "package.json").read_text(encoding="utf-8"))
        expected_sdk = package["dependencies"]["@anthropic-ai/claude-agent-sdk"]
        installed_package = (
            dest
            / "node_modules"
            / "@anthropic-ai"
            / "claude-agent-sdk"
            / "package.json"
        )
        try:
            installed_sdk = json.loads(
                installed_package.read_text(encoding="utf-8")
            ).get("version")
        except (OSError, json.JSONDecodeError):
            installed_sdk = None

        # Existing caches contain the old CLI-only package, so validate the
        # installed SDK instead of trusting that node_modules merely exists.
        if installed_sdk != expected_sdk:
            logger.info("Installing claude_code_runner dependencies...")
            subprocess.run(
                [npm_path, "install", "--omit=dev", "--include=optional"],
                cwd=str(dest),
                check=True,
                capture_output=True,
                timeout=120,
            )

        return dest

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute a query via the Claude Agent SDK subprocess.

        Spawns ``node index.mjs``, writes a JSON request to stdin, and
        reads sentinel-delimited JSON output from stdout.
        """
        denied = self._execution_denied_result()
        if denied is not None:
            return denied
        self._emit_turn_start(input)

        runner_dir = self._ensure_runner()

        # Build the request payload
        chat = self._mode == "chat"
        request = {
            "prompt": self._with_history(input, context) if chat else input,
            "workspace": self._workspace,
            "allowed_tools": [] if chat else (self._allowed_tools or []),
            "system_prompt": self._system_prompt
            or (_CHAT_SYSTEM_PROMPT if chat else ""),
            "session_id": self._session_id,
            "mode": self._mode,
        }

        try:
            if self._bus is not None:
                proc = self._run_streaming(runner_dir, request)
            else:
                proc = subprocess.run(
                    [self._node_executable, "index.mjs"],
                    cwd=str(runner_dir),
                    input=json.dumps(request),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self._timeout,
                )
        except subprocess.TimeoutExpired:
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"Claude Code agent timed out after {self._timeout}s.",
                turns=1,
                metadata={"error": True, "error_type": "timeout"},
            )

        if proc.returncode != 0:
            stderr = proc.stderr.strip() if proc.stderr else "Unknown error"
            logger.error(
                "claude_code_runner exited with code %d: %s",
                proc.returncode,
                stderr,
            )
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"Claude Code agent failed: {stderr}",
                turns=1,
                metadata={"error": True, "returncode": proc.returncode},
            )

        # Parse sentinel-delimited output
        content, tool_results, metadata = self._parse_output(proc.stdout)
        usage = metadata.get("usage") or {}
        if usage:
            # input_tokens only counts uncached input; add the cached context.
            prompt = (
                usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
            completion = usage.get("output_tokens", 0)
            metadata.update(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
            )

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=1,
            metadata=metadata,
        )

    @staticmethod
    def _with_history(input: str, context: Optional[AgentContext]) -> str:
        """Prefix the latest prior messages so chat mode keeps the conversation."""
        messages = list(context.conversation.messages) if context else []
        lines: list[str] = []
        for m in messages[-_HISTORY_MESSAGES:]:
            text = (m.content or "").strip()
            role = getattr(m.role, "value", str(m.role))
            if not text or role not in ("user", "assistant"):
                continue
            who = "Usuário" if role == "user" else "JARVIS"
            lines.append(f"{who}: {text}")
        history = "\n".join(lines)[-_HISTORY_MAX_CHARS:]
        if not history:
            return input
        return f"Conversa até agora:\n{history}\n\nUsuário: {input}"

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def _run_streaming(
        self, runner_dir: Path, request: dict[str, Any]
    ) -> "subprocess.CompletedProcess[str]":
        """Run the runner, publishing its live events on the event bus.

        Mirrors ``subprocess.run`` (same timeout semantics and return value)
        but reads stdout line by line so text and tool progress reach the
        bus while the query is still running.
        """
        proc = subprocess.Popen(
            [self._node_executable, "index.mjs"],
            cwd=str(runner_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            _kill_process_tree(proc)

        timer = threading.Timer(self._timeout, _kill)
        timer.start()
        stderr_chunks: list[str] = []
        stderr_thread = threading.Thread(
            target=lambda: stderr_chunks.append(proc.stderr.read()),
            daemon=True,
        )
        stderr_thread.start()
        stdout_lines: list[str] = []
        tool_starts: dict[str, tuple[str, float]] = {}
        try:
            try:
                assert proc.stdin is not None
                proc.stdin.write(json.dumps(request))
                proc.stdin.close()
            except OSError:
                pass  # runner died early; its exit code is reported below
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith(_EVENT_PREFIX):
                    self._publish_runner_event(line[len(_EVENT_PREFIX):], tool_starts)
                else:
                    stdout_lines.append(line)
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:  # error mid-read: never leave node running
                _kill_process_tree(proc)
                proc.wait()
            stderr_thread.join(timeout=2)
        if timed_out.is_set():
            raise subprocess.TimeoutExpired(
                cmd="node index.mjs", timeout=self._timeout
            )
        return subprocess.CompletedProcess(
            args=["node", "index.mjs"],
            returncode=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_chunks),
        )

    def _publish_runner_event(
        self, raw: str, tool_starts: dict[str, tuple[str, float]]
    ) -> None:
        """Translate one runner event line into an EventBus event."""
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        kind = event.get("type")
        if kind == "text_delta":
            self._bus.publish(
                EventType.AGENT_TEXT_DELTA,
                {"agent": self.agent_id, "text": event.get("text", "")},
            )
        elif kind == "tool_start":
            tool = str(event.get("tool", ""))
            tool_starts[str(event.get("id", ""))] = (tool, time.time())
            self._bus.publish(
                EventType.TOOL_CALL_START,
                {
                    "tool": tool,
                    "arguments": event.get("input") or {},
                    "agent": self.agent_id,
                },
            )
        elif kind == "tool_end":
            tool, started = tool_starts.pop(
                str(event.get("id", "")), ("", time.time())
            )
            self._bus.publish(
                EventType.TOOL_CALL_END,
                {
                    "tool": tool,
                    "success": bool(event.get("success", True)),
                    "latency": time.time() - started,
                    "result": event.get("content", ""),
                    "agent": self.agent_id,
                },
            )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_output(
        stdout: str,
    ) -> tuple[str, list[ToolResult], dict[str, Any]]:
        """Extract the sentinel-wrapped JSON from subprocess stdout.

        Returns ``(content, tool_results, metadata)``.
        """
        start = stdout.find(_OUTPUT_START)
        end = stdout.find(_OUTPUT_END)

        if start == -1 or end == -1:
            # No sentinels -- treat entire stdout as plain content
            return stdout.strip(), [], {}

        json_str = stdout[start + len(_OUTPUT_START) : end].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return stdout.strip(), [], {"parse_error": True}

        content = data.get("content", "")
        raw_tools = data.get("tool_results", [])
        metadata = data.get("metadata", {})

        tool_results = [
            ToolResult(
                tool_name=tr.get("tool_name", "unknown"),
                content=tr.get("content", ""),
                success=tr.get("success", True),
            )
            for tr in raw_tools
        ]

        return content, tool_results, metadata


__all__ = ["ClaudeCodeAgent"]
