"""AutoGen adapter -- intercepts AutoGen v0.4+ agent messages and runtime events.

AutoGen (autogen-agentchat >= 0.4) uses an event-driven architecture with typed
messages (TextMessage, ToolCallRequestEvent, HandoffMessage, etc.) and team-based
orchestration (RoundRobinGroupChat, SelectorGroupChat).  This adapter wraps the
team's ``run_stream`` method so every message that flows through the team is
translated into a PixelPulse event, giving real-time dashboard visibility.
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps
from typing import Any, AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message-type classification helpers
# ---------------------------------------------------------------------------

_TEXT_TYPES = ("TextMessage", "StopMessage", "HandoffMessage", "ToolCallSummaryMessage")
_EVENT_TYPES = ("ToolCallRequestEvent", "ToolCallExecutionEvent")
_TASK_RESULT_TYPE = "TaskResult"


def _type_name(obj: Any) -> str:
    """Return the class name of *obj* without importing the class."""
    return type(obj).__name__


def _safe_str(value: Any, max_len: int = 300) -> str:
    """Safely convert a value to a bounded string."""
    text = str(value) if value is not None else ""
    return text[:max_len] if len(text) > max_len else text


def _extract_source(message: Any) -> str:
    """Return the ``source`` field from a message or a safe fallback."""
    source = getattr(message, "source", None)
    if source:
        return str(source).lower().replace(" ", "-")
    return "unknown-agent"


def _extract_content(message: Any) -> str:
    """Return a human-readable content string from any AutoGen message."""
    content = getattr(message, "content", None)
    if content is None:
        return ""
    # ToolCallRequestEvent.content is a list of FunctionCall objects
    if isinstance(content, list):
        parts = []
        for item in content:
            if hasattr(item, "name"):
                # FunctionCall
                parts.append(f"tool:{item.name}({_safe_str(getattr(item, 'arguments', ''), 80)})")
            elif hasattr(item, "call_id"):
                # FunctionExecutionResult
                parts.append(f"result:{_safe_str(item.content, 80)}")
            else:
                parts.append(_safe_str(item, 80))
        return "; ".join(parts)
    return _safe_str(content)


# ---------------------------------------------------------------------------
# AutoGenAdapter
# ---------------------------------------------------------------------------


class AutoGenAdapter:
    """Adapter for Microsoft AutoGen agent framework (v0.4+).

    Usage::

        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.teams import RoundRobinGroupChat
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("autogen")
        adapter.instrument(team)

        # Now run the team -- events flow to the dashboard automatically
        result = await team.run(task="...")
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._team: Any | None = None
        self._agents: list[Any] = []
        self._original_run: Any | None = None
        self._original_run_stream: Any | None = None
        self._run_counter: int = 0
        self._active_agents: set[str] = set()
        self._last_source: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def instrument(self, team: Any) -> None:
        """Attach to an AutoGen team (or single agent).

        Wraps the team's ``run`` and ``run_stream`` methods to intercept
        every message that passes through the team during execution.

        Parameters
        ----------
        team:
            A ``RoundRobinGroupChat``, ``SelectorGroupChat``, or any object
            that exposes ``run`` / ``run_stream`` coroutines.  You may also
            pass a single ``AssistantAgent`` -- the adapter will wrap its
            ``on_messages`` method instead.
        """
        self._team = team

        # Discover agents registered with the team
        self._agents = self._discover_agents(team)

        # Wrap run / run_stream on team objects
        if hasattr(team, "run_stream"):
            self._original_run_stream = team.run_stream
            team.run_stream = self._wrapped_run_stream

        if hasattr(team, "run"):
            self._original_run = team.run
            team.run = self._wrapped_run

        # For single-agent usage (AssistantAgent), wrap on_messages
        if hasattr(team, "on_messages") and not hasattr(team, "run_stream"):
            self._wrap_single_agent(team)

        agent_count = len(self._agents) if self._agents else "unknown"
        logger.info("AutoGen adapter instrumented team with %s agents", agent_count)

    def detach(self) -> None:
        """Remove all instrumentation and restore original methods."""
        if self._team is None:
            return

        if self._original_run_stream is not None:
            self._team.run_stream = self._original_run_stream
        if self._original_run is not None:
            self._team.run = self._original_run

        self._original_run_stream = None
        self._original_run = None
        self._team = None
        self._agents = []
        self._active_agents.clear()
        self._last_source = None
        logger.info("AutoGen adapter detached")

    # ------------------------------------------------------------------
    # Agent discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _discover_agents(team: Any) -> list[Any]:
        """Pull out agent instances from a team object."""
        # RoundRobinGroupChat / SelectorGroupChat store agents in _participants
        for attr in ("_participants", "agents", "_agents"):
            agents = getattr(team, attr, None)
            if agents and isinstance(agents, (list, tuple)):
                return list(agents)
        return []

    # ------------------------------------------------------------------
    # Wrapped execution methods
    # ------------------------------------------------------------------

    def _next_run_id(self, task: Any = None) -> str:
        self._run_counter += 1
        return f"autogen-run-{self._run_counter}"

    async def _wrapped_run(self, *args: Any, **kwargs: Any) -> Any:
        """Wrap ``team.run()`` to emit run lifecycle + per-message events."""
        task = kwargs.get("task") or (args[0] if args else "")
        run_id = self._next_run_id(task)
        self._active_agents.clear()
        self._last_source = None

        self._pp.run_started(run_id, name=_safe_str(task, 120))
        start = time.monotonic()

        try:
            result = await self._original_run(*args, **kwargs)
            self._process_task_result(result, run_id)
            elapsed = time.monotonic() - start
            self._pp.run_completed(run_id, status="completed")
            logger.debug("AutoGen run %s completed in %.1fs", run_id, elapsed)
            return result
        except Exception as exc:
            self._pp.run_completed(run_id, status="error")
            self._emit_error_for_active_agents(str(exc))
            raise

    async def _wrapped_run_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """Wrap ``team.run_stream()`` to emit events for each streamed message."""
        task = kwargs.get("task") or (args[0] if args else "")
        run_id = self._next_run_id(task)
        self._active_agents.clear()
        self._last_source = None

        self._pp.run_started(run_id, name=_safe_str(task, 120))

        try:
            async for message in self._original_run_stream(*args, **kwargs):
                self._translate_message(message, run_id)
                yield message

            # Mark remaining active agents as idle
            self._idle_all_active_agents()
            self._pp.run_completed(run_id, status="completed")

        except Exception as exc:
            self._pp.run_completed(run_id, status="error")
            self._emit_error_for_active_agents(str(exc))
            raise

    # ------------------------------------------------------------------
    # Single-agent wrapping (on_messages)
    # ------------------------------------------------------------------

    def _wrap_single_agent(self, agent: Any) -> None:
        """Wrap a single agent's ``on_messages`` coroutine."""
        original_on_messages = agent.on_messages

        @wraps(original_on_messages)
        async def wrapped(messages: Any, cancellation_token: Any = None, **kw: Any) -> Any:
            agent_id = self._agent_id(agent)
            task_desc = ""
            if messages:
                first = messages[0] if isinstance(messages, list) else messages
                task_desc = _safe_str(getattr(first, "content", ""), 120)

            self._pp.agent_started(agent_id, task=task_desc)
            try:
                result = await original_on_messages(messages, cancellation_token, **kw)
                output = _safe_str(getattr(result, "chat_message", result), 300)
                self._pp.agent_completed(agent_id, output=output)
                return result
            except Exception as exc:
                self._pp.agent_error(agent_id, error=str(exc))
                raise

        agent.on_messages = wrapped

    # ------------------------------------------------------------------
    # Message translation
    # ------------------------------------------------------------------

    def _translate_message(self, message: Any, run_id: str) -> None:
        """Translate a single AutoGen message into PixelPulse event(s)."""
        name = _type_name(message)

        # TaskResult is the final summary -- not an agent message
        if name == _TASK_RESULT_TYPE:
            self._process_task_result(message, run_id)
            return

        source = _extract_source(message)
        content = _extract_content(message)

        # Emit agent_started for newly active agents
        if source not in self._active_agents and source != "unknown-agent":
            self._active_agents.add(source)
            task = content[:120] if content else ""
            self._pp.agent_started(source, task=task)

        # Emit inter-agent messages when the source changes
        if self._last_source and self._last_source != source and source != "unknown-agent":
            self._pp.agent_message(
                self._last_source,
                source,
                content=content[:200] if content else "continuation",
                tag=self._tag_for_message(name),
            )

        # Emit type-specific events
        if name in _TEXT_TYPES:
            self._on_text_message(source, content, name)
        elif name == "ToolCallRequestEvent":
            self._on_tool_call_request(source, content)
        elif name == "ToolCallExecutionEvent":
            self._on_tool_call_execution(source, content)
        elif name == "MultiModalMessage":
            self._on_multimodal_message(source, message)
        else:
            # Unknown message type -- emit as thinking
            if content:
                self._pp.agent_thinking(source, thought=f"[{name}] {content[:200]}")

        self._last_source = source

    def _on_text_message(self, source: str, content: str, msg_type: str) -> None:
        """Handle TextMessage, StopMessage, HandoffMessage, ToolCallSummaryMessage."""
        if msg_type == "StopMessage":
            self._pp.agent_completed(source, output=content)
            self._active_agents.discard(source)
        elif msg_type == "HandoffMessage":
            target = content  # HandoffMessage.content is the target agent name
            self._pp.agent_thinking(source, thought=f"Handing off to {target}")
        elif msg_type == "ToolCallSummaryMessage":
            self._pp.agent_thinking(source, thought=f"Tool result: {content[:200]}")
        else:
            # Regular TextMessage
            self._pp.agent_thinking(source, thought=content[:200])

    def _on_tool_call_request(self, source: str, content: str) -> None:
        """Handle ToolCallRequestEvent -- agent is invoking a tool."""
        self._pp.agent_thinking(source, thought=f"Calling tools: {content[:200]}")

    def _on_tool_call_execution(self, source: str, content: str) -> None:
        """Handle ToolCallExecutionEvent -- tool returned results."""
        self._pp.artifact_created(source, artifact_type="tool_result", content=content[:300])

    def _on_multimodal_message(self, source: str, message: Any) -> None:
        """Handle MultiModalMessage (text + images)."""
        content_parts = getattr(message, "content", [])
        text_parts = [str(p) for p in content_parts if isinstance(p, str)]
        image_count = len(content_parts) - len(text_parts)
        text = " ".join(text_parts)[:200]
        if image_count:
            self._pp.artifact_created(
                source, artifact_type="image", content=f"{image_count} image(s): {text}"
            )
        if text:
            self._pp.agent_thinking(source, thought=text)

    # ------------------------------------------------------------------
    # TaskResult handling
    # ------------------------------------------------------------------

    def _process_task_result(self, result: Any, run_id: str) -> None:
        """Extract final info from a TaskResult and emit completion events."""
        if result is None:
            return

        stop_reason = _safe_str(getattr(result, "stop_reason", ""), 120)
        messages = getattr(result, "messages", [])

        # Mark all previously active agents as completed
        self._idle_all_active_agents()

        # If the result has messages we haven't processed, emit the last one
        if messages:
            last = messages[-1]
            source = _extract_source(last)
            content = _extract_content(last)
            if content:
                self._pp.agent_completed(source, output=content[:300])

        if stop_reason:
            logger.debug("AutoGen run %s stopped: %s", run_id, stop_reason)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _idle_all_active_agents(self) -> None:
        """Mark all tracked active agents as completed/idle."""
        for agent_id in list(self._active_agents):
            self._pp.agent_completed(agent_id, output="")
        self._active_agents.clear()

    def _emit_error_for_active_agents(self, error: str) -> None:
        """Emit error events for all currently active agents."""
        for agent_id in list(self._active_agents):
            self._pp.agent_error(agent_id, error=error)
        self._active_agents.clear()

    @staticmethod
    def _agent_id(agent: Any) -> str:
        """Derive a dashboard-friendly agent ID from an agent object."""
        name = getattr(agent, "name", None)
        if name:
            return str(name).lower().replace(" ", "-")
        role = getattr(agent, "role", None)
        if role:
            return str(role).lower().replace(" ", "-")
        return "unknown-agent"

    @staticmethod
    def _tag_for_message(msg_type: str) -> str:
        """Map an AutoGen message type to a PixelPulse message tag."""
        tag_map = {
            "TextMessage": "data",
            "StopMessage": "control",
            "HandoffMessage": "handoff",
            "ToolCallSummaryMessage": "tool",
            "ToolCallRequestEvent": "tool",
            "ToolCallExecutionEvent": "tool",
            "MultiModalMessage": "data",
        }
        return tag_map.get(msg_type, "data")
