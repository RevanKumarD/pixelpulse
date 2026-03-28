"""CrewAI adapter — hooks into CrewAI's callback and event systems.

CrewAI provides ``step_callback`` and ``task_callback`` on the ``Crew`` class,
plus (since v0.70) a richer event listener API in ``crewai.utilities.events``.
This adapter translates both into PixelPulse events.

Supports CrewAI v0.60+ (callback-based) and v0.70+ (event-based).

Requires: ``pip install pixelpulse[crewai]``
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)

# Per-million-token pricing (input, output) — March 2026
# CrewAI can use any LLM provider, so we cover all major models.
# Sources: docs.anthropic.com, openai.com/api/pricing, ai.google.dev, api-docs.deepseek.com
# NOTE: Longer prefixes MUST come before shorter ones for correct matching
_TOKEN_COSTS_MTK: dict[str, tuple[float, float]] = {
    # ── OpenAI GPT-5.x (latest) ──
    "gpt-5.4-nano":    (0.20, 1.25),
    "gpt-5.4-mini":    (0.75, 4.50),
    "gpt-5.4-pro":     (30.00, 180.00),
    "gpt-5.4":         (2.50, 15.00),
    "gpt-5.3-codex":   (2.00, 10.00),
    "gpt-5.3":         (2.00, 10.00),
    "gpt-5.2":         (1.75, 14.00),
    "gpt-5-mini":      (0.25, 2.00),
    "gpt-5":           (1.25, 10.00),
    # ── OpenAI GPT-4.x (still available) ──
    "gpt-4.1-nano":    (0.10, 0.40),
    "gpt-4.1-mini":    (0.40, 1.60),
    "gpt-4.1":         (2.00, 8.00),
    "gpt-4o-mini":     (0.15, 0.60),
    "gpt-4o":          (2.50, 10.00),
    "o4-mini":         (1.10, 4.40),
    "o3":              (2.00, 8.00),
    # ── Anthropic Claude ──
    "claude-opus-4":   (5.0, 25.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4":  (1.0, 5.0),
    "claude-3.5-sonnet": (3.0, 15.0),
    "claude-3.5-haiku":  (0.80, 4.0),
    "claude-3-opus":   (15.0, 75.0),
    # ── Google Gemini 3.x (latest) ──
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro":  (2.00, 12.00),
    "gemini-3-flash":  (0.50, 3.00),
    # ── Google Gemini 2.x (still available) ──
    "gemini-2.5-pro":  (1.25, 10.00),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    # ── DeepSeek ──
    "deepseek":        (0.28, 0.42),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost from token counts and model name.

    Pricing is per million tokens. Prefix-matches model ID.
    """
    for prefix, (in_mtk, out_mtk) in _TOKEN_COSTS_MTK.items():
        if model and model.startswith(prefix):
            return (input_tokens / 1_000_000 * in_mtk) + (output_tokens / 1_000_000 * out_mtk)
    # Unknown model — conservative estimate at $2/$8 per MTok
    return (input_tokens / 1_000_000 * 2.0) + (output_tokens / 1_000_000 * 8.0)


def _sanitize_name(name: str | None) -> str:
    """Convert a role/agent name to a dashboard-friendly ID."""
    if not name:
        return "agent"
    return str(name).lower().replace(" ", "-").replace("_", "-")


def _extract_agent_role(output: Any) -> str:
    """Extract the agent role from a CrewAI output object."""
    # TaskOutput / step output may have an .agent with .role
    agent = getattr(output, "agent", None)
    if agent is not None:
        role = getattr(agent, "role", None)
        if role:
            return _sanitize_name(str(role))
        name = getattr(agent, "name", None)
        if name:
            return _sanitize_name(str(name))
    return "unknown-agent"


def _extract_token_usage(output: Any) -> dict[str, int]:
    """Extract token usage from CrewAI output if available.

    CrewAI stores token usage in different places depending on version:
    - TaskOutput.token_usage (dict with keys like total_tokens, prompt_tokens, etc.)
    - Usage info from the LLM callback (accumulated on the crew)
    """
    usage = getattr(output, "token_usage", None) or getattr(output, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {
            "input_tokens": usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0) or usage.get("output_tokens", 0),
        }
    # Object with attributes
    return {
        "input_tokens": getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0),
        "output_tokens": (
            getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0)
        ),
    }


class CrewAIAdapter:
    """Adapter for CrewAI agent framework.

    Usage::

        from crewai import Agent, Task, Crew
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("crewai")
        adapter.instrument(my_crew)

        # Now run the crew -- events will flow to the dashboard
        result = my_crew.kickoff()

        # When done:
        adapter.detach()
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._crew: Any = None
        self._original_callbacks: dict[str, Any] = {}
        self._original_kickoff: Any = None
        self._seen_agents: set[str] = set()
        self._task_start_times: dict[str, float] = {}
        self._run_counter: int = 0
        self._current_run_id: str = ""
        self._accumulated_cost: float = 0.0
        self._event_listeners_installed: bool = False

    def instrument(self, crew: Any) -> None:
        """Attach to a CrewAI Crew instance.

        Hooks into the crew's execution lifecycle to capture:
        - Run start/complete (via kickoff wrapping)
        - Agent task start/complete (via task_callback)
        - Agent thinking/tool use steps (via step_callback)
        - Token usage and cost (via output metadata)

        Supports both the callback API (v0.60+) and the event listener
        API (v0.70+). When both are available, events are deduplicated.

        Args:
            crew: A ``crewai.Crew`` instance.
        """
        self._crew = crew

        try:
            from crewai import Crew  # noqa: F401
        except ImportError:
            logger.error(
                "crewai package not installed. "
                "Install with: pip install pixelpulse[crewai]"
            )
            return

        # ---- Callback hooks (v0.60+) ----
        if hasattr(crew, "step_callback"):
            self._original_callbacks["step"] = crew.step_callback
            crew.step_callback = self._on_step

        if hasattr(crew, "task_callback"):
            self._original_callbacks["task"] = crew.task_callback
            crew.task_callback = self._on_task_complete

        # ---- Wrap kickoff for run lifecycle ----
        if hasattr(crew, "kickoff"):
            self._original_kickoff = crew.kickoff
            crew.kickoff = self._wrapped_kickoff

        # ---- Event listener API (v0.70+) ----
        self._try_install_event_listeners()

        agent_count = len(getattr(crew, "agents", []))
        logger.info("CrewAI adapter instrumented crew with %d agents", agent_count)

    def detach(self) -> None:
        """Remove instrumentation from the crew."""
        if self._crew is None:
            return

        if "step" in self._original_callbacks:
            self._crew.step_callback = self._original_callbacks["step"]
        if "task" in self._original_callbacks:
            self._crew.task_callback = self._original_callbacks["task"]
        if self._original_kickoff is not None:
            self._crew.kickoff = self._original_kickoff

        self._original_callbacks.clear()
        self._original_kickoff = None
        self._crew = None
        self._seen_agents.clear()
        self._task_start_times.clear()
        self._accumulated_cost = 0.0
        self._event_listeners_installed = False

    # ---- Kickoff wrapper (run lifecycle) ----

    def _wrapped_kickoff(self, *args: Any, **kwargs: Any) -> Any:
        """Wrap crew.kickoff() to emit run_started/run_completed events."""
        self._run_counter += 1
        self._current_run_id = f"crewai-run-{self._run_counter}"
        self._seen_agents.clear()
        self._accumulated_cost = 0.0

        crew_name = ""
        if self._crew is not None:
            crew_name = getattr(self._crew, "name", "") or ""
        run_name = crew_name or f"Crew Run #{self._run_counter}"

        self._pp.run_started(self._current_run_id, name=run_name)

        try:
            result = self._original_kickoff(*args, **kwargs)

            # Extract final token usage from CrewAI's accumulated metrics
            self._extract_crew_usage()

            self._pp.run_completed(
                self._current_run_id,
                status="completed",
                total_cost=self._accumulated_cost,
            )
            return result
        except Exception as exc:
            # Emit error for any active agents
            for agent_name in list(self._seen_agents):
                self._pp.agent_error(agent_name, error=str(exc)[:300])
            self._pp.run_completed(self._current_run_id, status="error")
            raise

    # ---- Step callback ----

    def _on_step(self, step_output: Any) -> None:
        """Called on each agent step (thinking, tool use, delegation)."""
        agent_name = _extract_agent_role(step_output)

        # Emit agent_started on first step from this agent in current run
        if agent_name not in self._seen_agents:
            self._seen_agents.add(agent_name)
            task_desc = self._get_current_task_description()
            self._pp.agent_started(agent_name, task=task_desc or "Processing")
            self._task_start_times[agent_name] = time.monotonic()

        # Determine step type and emit appropriate event
        # CrewAI step outputs vary by version:
        # - v0.60+: has .thought, .tool, .tool_input, .result attributes
        # - Some versions use AgentAction/AgentFinish from langchain
        thought = getattr(step_output, "thought", None)
        tool = getattr(step_output, "tool", None)
        tool_input = getattr(step_output, "tool_input", None)
        result = getattr(step_output, "result", None) or getattr(step_output, "output", None)
        text = getattr(step_output, "text", None)

        # Check for langchain-style AgentAction
        action = getattr(step_output, "action", None)
        if action is not None and tool is None:
            tool = getattr(action, "tool", None)
            tool_input = getattr(action, "tool_input", None)

        if tool:
            input_preview = ""
            if tool_input:
                input_preview = f"({str(tool_input)[:100]})"
            self._pp.agent_thinking(
                agent_name,
                thought=f"Using tool: {tool}{input_preview}",
            )
        elif thought:
            self._pp.agent_thinking(agent_name, thought=str(thought)[:300])
        elif text:
            self._pp.agent_thinking(agent_name, thought=str(text)[:300])

        # If this step produced a result, emit as artifact
        if result and tool:
            self._pp.artifact_created(
                agent_name,
                artifact_type="tool_result",
                content=f"{tool}: {str(result)[:200]}",
            )

        # Chain to original callback
        original = self._original_callbacks.get("step")
        if original:
            original(step_output)

    # ---- Task callback ----

    def _on_task_complete(self, task_output: Any) -> None:
        """Called when a task completes."""
        agent_name = _extract_agent_role(task_output)

        # Ensure agent_started was emitted
        if agent_name not in self._seen_agents:
            self._seen_agents.add(agent_name)
            self._pp.agent_started(agent_name, task="Processing")

        # Extract and emit cost/token usage
        usage = _extract_token_usage(task_output)
        if usage.get("input_tokens") or usage.get("output_tokens"):
            model = self._get_crew_model()
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cost = _estimate_cost(model, input_tokens, output_tokens)
            self._accumulated_cost += cost
            self._pp.cost_update(
                agent_name,
                cost=cost,
                tokens_in=input_tokens,
                tokens_out=output_tokens,
                model=model,
            )

        # Emit agent_completed
        output_text = ""
        raw = getattr(task_output, "raw", None) or getattr(task_output, "output", None)
        if raw:
            output_text = str(raw)[:300]
        elif hasattr(task_output, "description"):
            output_text = f"Completed: {task_output.description}"

        self._pp.agent_completed(agent_name, output=output_text or "Task completed")

        # Chain to original callback
        original = self._original_callbacks.get("task")
        if original:
            original(task_output)

    # ---- Event listener API (v0.70+) ----

    def _try_install_event_listeners(self) -> None:
        """Try to install CrewAI event listeners (available in v0.70+).

        The event bus moved from ``crewai.utilities.events`` (older) to
        ``crewai.events`` (current). We try both import paths.
        """
        crewai_event_bus = None
        try:
            from crewai.events import crewai_event_bus  # type: ignore[import-untyped]
        except ImportError:
            try:
                from crewai.utilities.events import crewai_event_bus  # type: ignore[import-untyped]
            except ImportError:
                # No event bus available — callback API only
                return

        if crewai_event_bus is None:
            return

        try:
            # Try current import path first, then legacy
            try:
                from crewai.events import (
                    AgentExecutionCompletedEvent as AgentExecutionCompleted,
                )
                from crewai.events import (  # type: ignore[import-untyped]
                    AgentExecutionStartedEvent as AgentExecutionStarted,
                )
                from crewai.events import (
                    ToolUsageFinishedEvent as ToolUsageFinished,
                )
                from crewai.events import (
                    ToolUsageStartedEvent as ToolUsageStarted,
                )
            except ImportError:
                from crewai.utilities.events.event_types import (  # type: ignore[import-untyped]
                    AgentExecutionCompleted,
                    AgentExecutionStarted,
                    ToolUsageFinished,
                    ToolUsageStarted,
                )

            @crewai_event_bus.on(AgentExecutionStarted)
            def on_agent_start(event: Any) -> None:
                agent_name = _sanitize_name(getattr(event, "agent_role", ""))
                if agent_name and agent_name not in self._seen_agents:
                    self._seen_agents.add(agent_name)
                    task = getattr(event, "task_description", "") or ""
                    self._pp.agent_started(agent_name, task=str(task)[:200])

            @crewai_event_bus.on(AgentExecutionCompleted)
            def on_agent_complete(event: Any) -> None:
                agent_name = _sanitize_name(getattr(event, "agent_role", ""))
                output = getattr(event, "output", "") or ""
                if agent_name:
                    self._pp.agent_completed(agent_name, output=str(output)[:300])

            @crewai_event_bus.on(ToolUsageStarted)
            def on_tool_start(event: Any) -> None:
                agent_name = _sanitize_name(getattr(event, "agent_role", ""))
                tool_name = getattr(event, "tool_name", "") or "unknown-tool"
                if agent_name:
                    self._pp.agent_thinking(
                        agent_name, thought=f"Using tool: {tool_name}"
                    )

            @crewai_event_bus.on(ToolUsageFinished)
            def on_tool_finish(event: Any) -> None:
                agent_name = _sanitize_name(getattr(event, "agent_role", ""))
                tool_name = getattr(event, "tool_name", "") or "unknown-tool"
                result = getattr(event, "result", None)
                if agent_name and result:
                    self._pp.artifact_created(
                        agent_name,
                        artifact_type="tool_result",
                        content=f"{tool_name}: {str(result)[:200]}",
                    )

            self._event_listeners_installed = True
            logger.info("CrewAI event listeners installed (v0.70+ API)")

        except (ImportError, AttributeError) as exc:
            # Event types may vary between versions — fall back to callbacks
            logger.debug("CrewAI event listener setup skipped: %s", exc)

    # ---- Helpers ----

    def _get_current_task_description(self) -> str:
        """Get the description of the currently executing task."""
        if self._crew is None:
            return ""
        tasks = getattr(self._crew, "tasks", [])
        for task in tasks:
            desc = getattr(task, "description", "")
            if desc:
                return str(desc)[:200]
        return ""

    def _get_crew_model(self) -> str:
        """Get the model name from the crew's agents."""
        if self._crew is None:
            return "unknown"
        agents = getattr(self._crew, "agents", [])
        for agent in agents:
            llm = getattr(agent, "llm", None)
            if llm is not None:
                model = getattr(llm, "model_name", None) or getattr(llm, "model", None)
                if model:
                    return str(model)
        return "unknown"

    def _extract_crew_usage(self) -> None:
        """Extract accumulated token usage from CrewAI's internal metrics."""
        if self._crew is None:
            return

        # CrewAI accumulates usage_metrics on the Crew after kickoff
        usage = getattr(self._crew, "usage_metrics", None)
        if usage is None:
            return

        if isinstance(usage, dict):
            total_tokens = usage.get("total_tokens", 0)
            if total_tokens and self._accumulated_cost == 0:
                # Rough cost estimate if we haven't tracked per-task
                prompt = usage.get("prompt_tokens", 0)
                completion = usage.get("completion_tokens", 0)
                model = self._get_crew_model()
                cost = _estimate_cost(model, prompt, completion)
                self._accumulated_cost = cost
