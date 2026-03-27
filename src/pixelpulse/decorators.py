"""@observe() decorator for universal function-level instrumentation.

Inspired by the Langfuse pattern, this module provides a single decorator
that works with sync and async functions, auto-emits PixelPulse events, and
supports nested spans via contextvars.

Usage::

    from pixelpulse import PixelPulse
    from pixelpulse.decorators import observe

    pp = PixelPulse(agents={...})

    @observe(pp, as_type="agent", name="researcher")
    def research(topic):
        return findings

    @observe(pp, as_type="tool")
    def web_search(query):
        return results
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import time
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

# Thread/async-safe context variable tracking the currently active agent span.
_current_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "pixelpulse_agent", default=None
)


def observe(
    pp: "PixelPulse",
    *,
    as_type: Literal["agent", "tool", "llm", "generation"] = "agent",
    name: str | None = None,
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable:
    """Decorate a function to auto-emit PixelPulse events.

    Works with both sync and async functions. Nested decorators propagate
    parent context so the dashboard can show parent-child relationships.

    Args:
        pp: The :class:`~pixelpulse.core.PixelPulse` instance to emit events to.
        as_type: Semantic type of the span. One of ``"agent"``, ``"tool"``,
            ``"llm"``, or ``"generation"``.  Determines which events are emitted.
        name: Override the span name. Defaults to the decorated function's name.
        capture_input: When ``True``, include formatted input args in the emitted
            event payload.
        capture_output: When ``True``, include a truncated string representation
            of the return value in the emitted event payload.

    Returns:
        A decorator that wraps the target function.

    Examples::

        @observe(pp, as_type="agent", name="researcher")
        def research(topic):
            return findings

        @observe(pp, as_type="tool")
        async def fetch_page(url):
            ...
    """

    def decorator(func: Callable) -> Callable:
        agent_name = name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            parent = _current_agent.get()
            token = _current_agent.set(agent_name)

            start = time.monotonic()
            task_desc = _format_input(args, kwargs) if capture_input else as_type

            _emit_start(pp, as_type, agent_name, parent, task_desc)

            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.monotonic() - start) * 1000)
                output = _format_output(result) if capture_output else ""
                _emit_success(pp, as_type, agent_name, parent, output, duration_ms)
                return result
            except Exception as exc:
                _emit_error(pp, as_type, agent_name, exc)
                raise
            finally:
                _current_agent.reset(token)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            parent = _current_agent.get()
            token = _current_agent.set(agent_name)

            start = time.monotonic()
            task_desc = _format_input(args, kwargs) if capture_input else as_type

            _emit_start(pp, as_type, agent_name, parent, task_desc)

            try:
                result = await func(*args, **kwargs)
                duration_ms = int((time.monotonic() - start) * 1000)
                output = _format_output(result) if capture_output else ""
                _emit_success(pp, as_type, agent_name, parent, output, duration_ms)
                return result
            except Exception as exc:
                _emit_error(pp, as_type, agent_name, exc)
                raise
            finally:
                _current_agent.reset(token)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ---- Private helpers ----


def _emit_start(
    pp: "PixelPulse",
    as_type: str,
    agent_name: str,
    parent: str | None,
    task_desc: str,
) -> None:
    """Emit the appropriate start event based on *as_type*."""
    if as_type == "agent":
        pp.agent_started(agent_name, task=task_desc[:200])
    elif as_type in ("tool", "llm", "generation"):
        effective_parent = parent or agent_name
        pp.agent_thinking(
            effective_parent,
            thought=f"Using {as_type}: {agent_name}",
        )


def _emit_success(
    pp: "PixelPulse",
    as_type: str,
    agent_name: str,
    parent: str | None,
    output: str,
    duration_ms: int,
) -> None:
    """Emit the appropriate completion event based on *as_type*."""
    if as_type == "agent":
        pp.agent_completed(
            agent_name,
            output=output or f"Completed in {duration_ms}ms",
        )
    elif as_type in ("tool", "llm", "generation"):
        effective_parent = parent or agent_name
        pp.artifact_created(
            effective_parent,
            artifact_type="tool_result",
            content=f"{agent_name}: {output[:200]}",
        )


def _emit_error(
    pp: "PixelPulse",
    as_type: str,
    agent_name: str,
    exc: Exception,
) -> None:
    """Emit an error event when the decorated function raises."""
    if as_type == "agent":
        pp.agent_error(agent_name, error=str(exc)[:300])


def _format_input(args: tuple, kwargs: dict) -> str:
    """Format function arguments into a short human-readable string."""
    parts = [str(a)[:50] for a in args[:3]]
    parts += [f"{k}={str(v)[:30]}" for k, v in list(kwargs.items())[:3]]
    return ", ".join(parts) or "no input"


def _format_output(result: object) -> str:
    """Format a return value into a short string representation."""
    if result is None:
        return ""
    return str(result)[:300]
