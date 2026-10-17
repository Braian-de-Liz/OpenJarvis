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
import re
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
from openjarvis.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    ApprovalStore,
)

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


# Claude model picked in the HUD travels as a suffix of the request model:
# "claude-code:opus" / "claude-code-agent:claude-sonnet-4-5". Only plain
# model ids/aliases are accepted.
_CLAUDE_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\]]{0,63}$")


AGENT_TOOLS_ENV = "OPENJARVIS_CLAUDE_AGENT_TOOLS"


def agent_tools_from_env() -> List[str]:
    """Explicit opt-in tool list for agent mode, e.g. ``Read,Grep,Edit``.

    Empty (the default) means the runner's read-only set. Naming a tool here
    both makes it available and pre-approves it, so writing or running commands
    is always a deliberate choice made outside the HUD.
    """
    raw = os.environ.get(AGENT_TOOLS_ENV, "")
    return [name for name in (part.strip() for part in raw.split(",")) if name]


PERMISSIONS = ("read", "ask", "free")


def split_claude_id(model: str) -> tuple[str, str, str]:
    """Split ``base[:claude_model][@permission]`` into its three parts."""
    rest, _, permission = (model or "").partition("@")
    base, sep, claude_model = rest.partition(":")
    return base, (claude_model if sep else ""), permission


def claude_model_from(model: str) -> str:
    """Return the Claude model part of a ``claude-code[:model][@perm]`` id, or ''."""
    suffix = split_claude_id(model)[1]
    return suffix if _CLAUDE_MODEL_RE.match(suffix) else ""


def permission_from(model: str) -> str:
    """Agent permission mode of a model id: read (default) / ask / free."""
    permission = split_claude_id(model)[2]
    return permission if permission in PERMISSIONS else "read"


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


class _Deadline:
    """A timeout clock that stops while we wait for the user to decide."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds
        self._paused_at: Optional[float] = None
        self._lock = threading.Lock()

    def pause(self) -> None:
        with self._lock:
            if self._paused_at is None:
                self._paused_at = time.monotonic()

    def resume(self) -> None:
        with self._lock:
            if self._paused_at is not None:
                self._end += time.monotonic() - self._paused_at
                self._paused_at = None

    def expired(self) -> bool:
        with self._lock:
            return self._paused_at is None and time.monotonic() > self._end


def describe_permission(
    tool: str, tool_input: dict[str, Any], reason: Any = None
) -> str:
    """One readable line for the HUD approval card."""
    if tool == "Bash":
        text = f"Rodar comando: {str(tool_input.get('command', ''))[:300]}"
    elif tool in ("Edit", "NotebookEdit"):
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or "?"
        text = f"Editar arquivo: {target}"
    elif tool == "Write":
        text = f"Criar ou sobrescrever arquivo: {tool_input.get('file_path', '?')}"
    else:
        text = f"Usar a ferramenta {tool}"
    return f"{text} ({reason})" if reason else text


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
        approval_store: Optional[Any] = None,
        approval_timeout: float = 180.0,
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
        # Where "ask" decisions are queued so the HUD can show Aprovar/Negar.
        self._approval_store = approval_store
        self._approval_timeout = approval_timeout

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
            "allowed_tools": (
                [] if chat else (self._allowed_tools or agent_tools_from_env() or [])
            ),
            "system_prompt": self._system_prompt
            or (_CHAT_SYSTEM_PROMPT if chat else ""),
            "session_id": self._session_id,
            "mode": self._mode,
            # read (default) / ask / free; see the runner's tool policy.
            "permission": permission_from(self._model),
            # Questions can only be answered over the streaming channel.
            "interactive": self._bus is not None,
        }
        claude_model = claude_model_from(self._model)
        if claude_model:
            request["model"] = claude_model

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
            logger.info(
                "claude_code usage (%s): input=%s cache_read=%s cache_create=%s "
                "output=%s turns=%s model=%s",
                self._mode,
                usage.get("input_tokens", 0),
                usage.get("cache_read_input_tokens", 0),
                usage.get("cache_creation_input_tokens", 0),
                completion,
                metadata.get("num_turns"),
                metadata.get("model"),
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
        bus while the query is still running. stdin stays open after the
        request so permission decisions can be written back; time spent
        waiting for the user does not count against the timeout.
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
        finished = threading.Event()
        deadline = _Deadline(self._timeout)

        def _watchdog() -> None:
            while not finished.wait(min(0.1, max(self._timeout / 5, 0.01))):
                if deadline.expired():
                    timed_out.set()
                    _kill_process_tree(proc)
                    return

        watchdog = threading.Thread(target=_watchdog, daemon=True)
        watchdog.start()
        stderr_chunks: list[str] = []
        stderr_thread = threading.Thread(
            target=lambda: stderr_chunks.append(proc.stderr.read()),
            daemon=True,
        )
        stderr_thread.start()
        stdout_lines: list[str] = []
        tool_starts: dict[str, tuple[str, float]] = {}

        def _on_permission(event: dict[str, Any]) -> None:
            deadline.pause()  # the user's thinking time is not the model's
            try:
                allowed = self._ask_user(event, proc)
            finally:
                deadline.resume()
            self._send_decision(proc, str(event.get("id", "")), allowed)

        try:
            try:
                assert proc.stdin is not None
                # One line: the request. stdin stays open for decisions.
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
            except OSError:
                pass  # runner died early; its exit code is reported below
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith(_EVENT_PREFIX):
                    self._publish_runner_event(
                        line[len(_EVENT_PREFIX) :],
                        tool_starts,
                        on_permission=_on_permission,
                    )
                else:
                    stdout_lines.append(line)
            proc.wait()
        finally:
            finished.set()
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:  # error mid-read: never leave node running
                _kill_process_tree(proc)
                proc.wait()
            stderr_thread.join(timeout=2)
            watchdog.join(timeout=2)
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

    # ------------------------------------------------------------------
    # Permission questions
    # ------------------------------------------------------------------

    def _store(self) -> Any:
        if self._approval_store is None:
            self._approval_store = ApprovalStore()
        return self._approval_store

    def _ask_user(self, event: dict[str, Any], proc: Any) -> bool:
        """Queue the question for the HUD and wait for Aprovar/Negar.

        True only on an explicit approval. Timeout, a dead runner or any error
        mean "no": the safe answer is always to deny.
        """
        tool = str(event.get("tool", ""))
        tool_input = event.get("input") or {}
        try:
            store = self._store()
            action = store.queue_action(
                action_type=f"claude_code:{tool}",
                description=describe_permission(
                    tool, tool_input, event.get("reason")
                ),
                payload={
                    "tool": tool,
                    "input": tool_input,
                    "reason": event.get("reason", ""),
                    "blocked_path": event.get("blocked_path", ""),
                },
                permission_key=f"claude_code:{tool}",
                tier="high" if tool == "Bash" else "medium",
                ttl_hours=1,
            )
        except Exception:
            logger.warning("Could not queue the approval request", exc_info=True)
            return False

        limit = time.monotonic() + self._approval_timeout
        while time.monotonic() < limit and proc.poll() is None:
            try:
                current = store.get_action(action.id)
            except Exception:
                logger.warning("Could not read the approval status", exc_info=True)
                return False
            if current is None:
                return False
            if current.status != STATUS_PENDING:
                return current.status == STATUS_APPROVED
            time.sleep(0.25)
        try:
            store.update_status(action.id, STATUS_EXPIRED)
        except Exception:
            logger.debug("Could not expire the approval request", exc_info=True)
        return False

    @staticmethod
    def _send_decision(proc: Any, request_id: str, allowed: bool) -> None:
        try:
            assert proc.stdin is not None
            message = {
                "type": "permission_decision",
                "id": request_id,
                "allow": allowed,
            }
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            pass  # the runner is gone; it denies on EOF anyway

    def _log_context_debug(self, event: dict[str, Any]) -> None:
        """Log what the Claude Code session loaded (names and counts only)."""

        def _names(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(item)[:80] for item in value[:50]]

        servers = event.get("mcp_servers")
        mcp = [
            f"{str(s.get('name', ''))[:80]}({str(s.get('status', ''))[:20]})"
            for s in (servers if isinstance(servers, list) else [])[:50]
            if isinstance(s, dict)
        ]
        logger.info(
            "claude_code context (%s): model=%s tools=%s mcp_servers=%s "
            "plugins=%s skills=%s slash_commands=%s",
            self._mode,
            str(event.get("model", ""))[:80],
            _names(event.get("tools")),
            mcp,
            _names(event.get("plugins")),
            event.get("skills", 0),
            event.get("slash_commands", 0),
        )

    def _publish_runner_event(
        self,
        raw: str,
        tool_starts: dict[str, tuple[str, float]],
        on_permission: Optional[Any] = None,
    ) -> None:
        """Translate one runner event line into an EventBus event."""
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        kind = event.get("type")
        if kind == "permission_request":
            if on_permission is not None:
                on_permission(event)
        elif kind == "context_debug":
            # Only emitted when OPENJARVIS_CLAUDE_DEBUG_CONTEXT=1. Log-only:
            # what Claude Code loaded for this session (names and counts).
            self._log_context_debug(event)
        elif kind == "model":
            self._bus.publish(
                EventType.AGENT_MODEL_INFO,
                {"agent": self.agent_id, "model": str(event.get("model", ""))},
            )
        elif kind == "text_delta":
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
