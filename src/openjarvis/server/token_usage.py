"""Token usage for direct (non-agent) streaming responses.

Engines such as Ollama measure prompt/completion tokens while streaming and
keep them on ``_last_stream_usage``, but the streaming route never sent them,
so the UI could not show tokens or how full the context window is.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from openjarvis.core.types import Message
from openjarvis.engine._base import estimate_prompt_tokens

_WRAPPER_ATTRS = ("_inner", "_engine")


def stream_usage_owner(engine: Any, model: str) -> Optional[Any]:
    """Find the concrete engine that serves *model* and records stream usage.

    Unwraps instrumentation/guardrail wrappers (``_inner`` / ``_engine``) and
    asks a ``MultiEngine`` which backend owns the model.
    """
    seen: set[int] = set()
    current = engine
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if hasattr(current, "_last_stream_usage"):
            return current
        engine_for = getattr(current, "_engine_for", None)
        if callable(engine_for):
            try:
                current = engine_for(model)
                continue
            except Exception:
                return None
        current = next(
            (getattr(current, a) for a in _WRAPPER_ATTRS if hasattr(current, a)),
            None,
        )
    return None


def snapshot(owner: Optional[Any]) -> Any:
    """Identity of the owner's current usage record (taken before streaming)."""
    return getattr(owner, "_last_stream_usage", None) if owner is not None else None


def stream_usage(
    owner: Optional[Any],
    before: Any,
    messages: Sequence[Message],
    completion_text: str,
) -> Dict[str, Any]:
    """Usage for the stream that just finished.

    Uses the engine's own count when it recorded a *new* one during this
    stream (the record object changes on completion); otherwise estimates
    (~4 chars per token) and marks the result ``estimated``.
    """
    current = snapshot(owner)
    if isinstance(current, dict) and current is not before and current:
        prompt = int(current.get("prompt_tokens", 0))
        completion = int(current.get("completion_tokens", 0))
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
    prompt = estimate_prompt_tokens(messages) if messages else 0
    completion = max(1, len(completion_text) // 4) if completion_text else 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "estimated": True,
    }


__all__ = ["snapshot", "stream_usage", "stream_usage_owner"]
