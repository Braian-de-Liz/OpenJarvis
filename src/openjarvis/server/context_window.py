"""How big is the context window for the model the HUD is using?

``GET /api/context-window?model=…`` returns::

    {"model": ..., "window": int | None, "model_max": int | None,
     "source": str, "history_limit": {"messages": n, "chars": n} | None}

* Local (Ollama) models: the effective window is ``num_ctx`` — what
  OpenJarvis asks Ollama for (``JARVIS_NUM_CTX``, default 16 384) — capped by
  the model's own ``context_length`` from ``/api/show``. Beyond it Ollama
  silently drops the start of the conversation.
* Claude Code (``claude-code[-agent][:model]``): 200k tokens. Conversation
  mode only sends the last messages (see ``agents/claude_code.py``), which is
  reported as ``history_limit``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

CLAUDE_WINDOW = 200_000
_CLAUDE_IDS = ("claude-code", "claude-code-agent")


def _num_ctx() -> int:
    from openjarvis.engine.ollama import _default_num_ctx

    return _default_num_ctx()


def _ollama_context_length(model: str) -> Optional[int]:
    """The model's maximum context from Ollama ``/api/show`` (None if unknown)."""
    import httpx

    from openjarvis.core.config import load_config

    host = (load_config().engine.ollama.host or "http://localhost:11434").rstrip("/")
    resp = httpx.post(f"{host}/api/show", json={"model": model}, timeout=5.0)
    resp.raise_for_status()
    info = resp.json().get("model_info") or {}
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


def describe_window(
    model: str,
    *,
    show: Callable[[str], Optional[int]] = _ollama_context_length,
    num_ctx: Callable[[], int] = _num_ctx,
) -> Dict[str, Any]:
    base = re.split("[:@]", model, maxsplit=1)[0]
    if base in _CLAUDE_IDS:
        from openjarvis.agents.claude_code import (
            _HISTORY_MAX_CHARS,
            _HISTORY_MESSAGES,
        )

        chat = base == "claude-code"
        return {
            "model": model,
            "window": CLAUDE_WINDOW,
            "model_max": CLAUDE_WINDOW,
            "source": "claude",
            "history_limit": (
                {"messages": _HISTORY_MESSAGES, "chars": _HISTORY_MAX_CHARS}
                if chat
                else None
            ),
        }

    configured = num_ctx()
    try:
        model_max = show(model)
    except Exception:
        logger.debug("context_length lookup failed for %s", model, exc_info=True)
        model_max = None
    if model_max is None:
        # Not an Ollama model we can inspect: report what we would ask for.
        return {
            "model": model,
            "window": configured,
            "model_max": None,
            "source": "num_ctx",
            "history_limit": None,
        }
    return {
        "model": model,
        "window": min(configured, model_max),
        "model_max": model_max,
        "source": "ollama num_ctx",
        "history_limit": None,
    }


def create_context_window_router(
    *,
    show: Callable[[str], Optional[int]] = _ollama_context_length,
    num_ctx: Callable[[], int] = _num_ctx,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["context"])
    cache: Dict[str, Optional[int]] = {}

    def cached_show(model: str) -> Optional[int]:
        if model not in cache:
            cache[model] = show(model)
        return cache[model]

    @router.get("/context-window")
    def context_window(model: str = Query(..., min_length=1)) -> Dict[str, Any]:
        return describe_window(model, show=cached_show, num_ctx=num_ctx)

    return router


__all__ = ["CLAUDE_WINDOW", "create_context_window_router", "describe_window"]
