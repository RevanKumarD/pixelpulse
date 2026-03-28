"""OpenAI Agents SDK adapter — hooks into the SDK's tracing system.

The OpenAI Agents SDK has a built-in tracing architecture with:
- Traces: end-to-end workflow executions
- Spans: individual operations (agent, generation, function, handoff, guardrail)

This adapter implements TracingProcessor to intercept all spans and translate
them into PixelPulse dashboard events in real time.

Requires: pip install pixelpulse[openai]
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)

# Approximate cost per 1K tokens for common models (for cost estimation)
# Sorted longest-prefix-first so "gpt-4o-mini" matches before "gpt-4o"
# Per-million-token pricing (input, output) — March 2026
# Sources: openai.com/api/pricing, platform.openai.com/docs/pricing
_TOKEN_COSTS_MTK: dict[str, tuple[float, float]] = {
    # GPT-4.1 family
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1":      (2.00, 8.00),
    # GPT-4o family
    "gpt-4o-mini":  (0.15, 0.60),
    "gpt-4o":       (2.50, 10.00),
    # o-series reasoning
    "o4-mini":      (1.10, 4.40),
    "o3":           (2.00, 8.00),
    # GPT-5
    "gpt-5":        (2.00, 8.00),      # placeholder — update when released
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost from token counts and model name.

    Pricing is per million tokens. Prefix-matches so 'gpt-4.1-mini-2025-04-14'
    matches 'gpt-4.1-mini' (checked before 'gpt-4.1' due to dict order).
    """
    for prefix, (in_mtk, out_mtk) in _TOKEN_COSTS_MTK.items():
        if model and model.startswith(prefix):
            return (input_tokens / 1_000_000 * in_mtk) + (output_tokens / 1_000_000 * out_mtk)
    # Unknown model — fall back to GPT-4.1-mini pricing ($0.40/$1.60 per MTok)
    return (input_tokens / 1_000_000 * 0.40) + (output_tokens / 1_000_000 * 1.60)


class OpenAIAgentsAdapter:
    """Adapter for the OpenAI Agents SDK.

    Usage::

        from agents import Agent, Runner
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("openai")
        adapter.instrument()  # registers the tracing processor globally

        # Now run agents — events flow to the dashboard automatically
        result = Runner.run_sync(agent, "Hello!")

        # When done:
        adapter.detach()
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._processor: Any = None
        self._installed = False

    def instrument(self, agent: Any = None) -> None:
        """Register a PixelPulse tracing processor with the OpenAI Agents SDK.

        The processor intercepts all traces and spans globally — you don't need
        to pass an agent instance. If ``agent`` is provided, its name is recorded
        for better labeling but instrumentation is still global.

        Args:
            agent: Optional Agent instance. Used for initial metadata only.
        """
        try:
            from agents.tracing import add_trace_processor
        except ImportError:
            logger.error(
                "openai-agents package not installed. "
                "Install with: pip install pixelpulse[openai]"
            )
            return

        self._processor = _PixelPulseTracingProcessor(self._pp)
        add_trace_processor(self._processor)
        self._installed = True

        agent_name = ""
        if agent is not None:
            agent_name = getattr(agent, "name", str(agent))
        logger.info(
            "OpenAI Agents SDK adapter instrumented%s",
            f" (root agent: {agent_name})" if agent_name else "",
        )

    def detach(self) -> None:
        """Shut down the tracing processor."""
        if self._processor is not None:
            self._processor.shutdown()
            self._processor = None
        self._installed = False


class _PixelPulseTracingProcessor:
    """Implements the OpenAI Agents SDK TracingProcessor protocol.

    Receives trace and span lifecycle events and translates them into
    PixelPulse dashboard events.

    Span types handled:
    - agent: Agent execution (name, handoffs, tools, output_type)
    - generation: LLM call (model, input, output, usage)
    - function: Tool/function call (name, input, output)
    - handoff: Agent-to-agent handoff (from_agent, to_agent)
    - guardrail: Guardrail check (name, triggered)
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._active_traces: dict[str, dict] = {}
        self._active_agents: dict[str, str] = {}  # span_id → agent_name
        self._span_start_times: dict[str, float] = {}
        self._trace_costs: dict[str, float] = {}  # trace_id → accumulated cost

    # ---- Trace lifecycle ----

    def on_trace_start(self, trace: Any) -> None:
        """Called when a new trace (workflow execution) begins."""
        trace_id = getattr(trace, "trace_id", "") or ""
        name = getattr(trace, "name", "") or "agent-run"

        self._active_traces[trace_id] = {"name": name}
        self._trace_costs[trace_id] = 0.0
        self._pp.run_started(trace_id, name=name)

    def on_trace_end(self, trace: Any) -> None:
        """Called when a trace completes."""
        trace_id = getattr(trace, "trace_id", "") or ""
        total_cost = self._trace_costs.pop(trace_id, 0.0)
        self._active_traces.pop(trace_id, None)
        self._pp.run_completed(trace_id, status="completed", total_cost=total_cost)

    # ---- Span lifecycle ----

    def on_span_start(self, span: Any) -> None:
        """Called when a span begins — dispatch based on span data type."""
        span_id = getattr(span, "span_id", "") or ""
        self._span_start_times[span_id] = time.monotonic()

        span_data = getattr(span, "span_data", None)
        if span_data is None:
            return

        span_type = getattr(span_data, "type", "")

        if span_type == "agent":
            agent_name = _sanitize_name(getattr(span_data, "name", "agent"))
            self._active_agents[span_id] = agent_name
            tools = getattr(span_data, "tools", None) or []
            handoffs = getattr(span_data, "handoffs", None) or []
            task_desc = ""
            if tools:
                task_desc = f"Tools: {', '.join(tools[:5])}"
            if handoffs:
                task_desc += f" | Handoffs: {', '.join(handoffs[:3])}"
            self._pp.agent_started(agent_name, task=task_desc or "Processing")

        elif span_type == "function":
            func_name = getattr(span_data, "name", "unknown-function")
            func_input = getattr(span_data, "input", "")
            # Find the parent agent for this function call
            parent_agent = self._find_parent_agent(span)
            self._pp.agent_thinking(
                parent_agent,
                thought=f"Calling tool: {func_name}"
                + (f"({str(func_input)[:100]})" if func_input else ""),
            )

        elif span_type == "handoff":
            from_agent = _sanitize_name(getattr(span_data, "from_agent", "?"))
            to_agent = _sanitize_name(getattr(span_data, "to_agent", "?"))
            self._pp.agent_message(
                from_agent,
                to_agent,
                content=f"Handoff from {from_agent} to {to_agent}",
                tag="handoff",
            )

        elif span_type == "guardrail":
            name = getattr(span_data, "name", "guardrail")
            parent_agent = self._find_parent_agent(span)
            self._pp.agent_thinking(parent_agent, thought=f"Guardrail check: {name}")

    def on_span_end(self, span: Any) -> None:
        """Called when a span completes — extract results and emit events."""
        span_id = getattr(span, "span_id", "") or ""
        self._span_start_times.pop(span_id, None)

        span_data = getattr(span, "span_data", None)
        if span_data is None:
            return

        span_type = getattr(span_data, "type", "")
        error = getattr(span, "error", None)

        if span_type == "agent":
            agent_name = self._active_agents.pop(span_id, "agent")
            if error:
                self._pp.agent_error(agent_name, error=str(error))
            else:
                output_type = getattr(span_data, "output_type", "") or ""
                self._pp.agent_completed(
                    agent_name,
                    output=f"Completed (output: {output_type})" if output_type else "Completed",
                )

        elif span_type == "generation":
            model = getattr(span_data, "model", "") or "unknown"
            usage = getattr(span_data, "usage", None) or {}
            input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
            output_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)

            parent_agent = self._find_parent_agent(span)

            # Emit thinking with model info
            output_msgs = getattr(span_data, "output", None) or []
            if output_msgs and isinstance(output_msgs, (list, tuple)):
                # Extract the last assistant message content
                for msg in reversed(output_msgs):
                    content = ""
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                    if content:
                        self._pp.agent_thinking(
                            parent_agent,
                            thought=str(content)[:300],
                        )
                        break

            # Emit cost update
            if input_tokens or output_tokens:
                cost = _estimate_cost(model, input_tokens, output_tokens)
                self._pp.cost_update(
                    parent_agent,
                    cost=cost,
                    tokens_in=input_tokens,
                    tokens_out=output_tokens,
                    model=model,
                )
                # Accumulate trace cost
                trace_id = self._find_trace_id(span)
                if trace_id in self._trace_costs:
                    self._trace_costs[trace_id] += cost

        elif span_type == "function":
            func_name = getattr(span_data, "name", "unknown")
            func_output = getattr(span_data, "output", None)
            parent_agent = self._find_parent_agent(span)

            if error:
                self._pp.agent_thinking(
                    parent_agent,
                    thought=f"Tool {func_name} failed: {str(error)[:200]}",
                )
            elif func_output is not None:
                output_str = str(func_output)[:200]
                self._pp.artifact_created(
                    parent_agent,
                    artifact_type="tool_result",
                    content=f"{func_name}: {output_str}",
                )

        elif span_type == "guardrail":
            triggered = getattr(span_data, "triggered", False)
            name = getattr(span_data, "name", "guardrail")
            parent_agent = self._find_parent_agent(span)
            if triggered:
                self._pp.agent_thinking(
                    parent_agent,
                    thought=f"Guardrail '{name}' triggered — blocking output",
                )

    def shutdown(self) -> None:
        """Clean up resources."""
        self._active_traces.clear()
        self._active_agents.clear()
        self._span_start_times.clear()
        self._trace_costs.clear()

    def force_flush(self) -> None:
        """No batching — events are emitted immediately."""
        pass

    # ---- Helpers ----

    def _find_parent_agent(self, span: Any) -> str:
        """Walk up the span tree to find the enclosing agent name."""
        parent = getattr(span, "parent", None)
        while parent is not None:
            parent_id = getattr(parent, "span_id", "")
            if parent_id in self._active_agents:
                return self._active_agents[parent_id]
            parent = getattr(parent, "parent", None)

        # Fallback: return the most recently started agent
        if self._active_agents:
            return next(reversed(self._active_agents.values()))
        return "agent"

    def _find_trace_id(self, span: Any) -> str:
        """Extract the trace_id from a span's trace context."""
        trace = getattr(span, "trace", None) or getattr(span, "_trace", None)
        if trace:
            return getattr(trace, "trace_id", "")
        parent = getattr(span, "parent", None)
        if parent:
            return self._find_trace_id(parent)
        return ""


def _sanitize_name(name: str | None) -> str:
    """Convert an agent/tool name to a dashboard-friendly ID."""
    if not name:
        return "agent"
    return str(name).lower().replace(" ", "-").replace("_", "-")
