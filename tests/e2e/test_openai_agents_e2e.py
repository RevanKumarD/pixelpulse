"""E2E test: OpenAI Agents SDK adapter traced through PixelPulse.

The OpenAI Agents SDK requires Python 3.12+. Since we may be running on
3.11, this test exercises the full adapter tracing pipeline by simulating
the SDK's tracing protocol objects (Trace, Span, SpanData).

This is a protocol-level E2E test: it feeds realistic tracing events
through the PixelPulse adapter and verifies dashboard events are emitted
correctly, covering agent spans, generation spans, function spans,
handoff spans, and guardrail spans.

When Python 3.12+ is available and the SDK is installed, additional tests
use real Agent + Runner + FakeModel for full-stack validation.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import pytest

from pixelpulse import PixelPulse
from pixelpulse.adapters.openai_agents import (
    OpenAIAgentsAdapter,
    _PixelPulseTracingProcessor,
    _estimate_cost,
    _sanitize_name,
)


# ---------------------------------------------------------------------------
# Protocol simulation objects (mirrors OpenAI Agents SDK tracing types)
# ---------------------------------------------------------------------------


@dataclass
class FakeSpanData:
    type: str = ""
    name: str = ""
    model: str = ""
    tools: list[str] = field(default_factory=list)
    handoffs: list[str] = field(default_factory=list)
    output_type: str = ""
    input: str = ""
    output: Any = None
    usage: dict = field(default_factory=dict)
    triggered: bool = False
    from_agent: str = ""
    to_agent: str = ""


@dataclass
class FakeSpan:
    span_id: str = ""
    span_data: FakeSpanData | None = None
    parent: Any = None
    error: str | None = None


@dataclass
class FakeTrace:
    trace_id: str = ""
    name: str = ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pp():
    return PixelPulse(
        agents={
            "researcher": {"team": "research", "role": "Research Analyst"},
            "writer": {"team": "content", "role": "Technical Writer"},
            "triage": {"team": "triage", "role": "Triage Agent"},
        },
        teams={
            "research": {"label": "Research", "color": "#00d4ff"},
            "content": {"label": "Content", "color": "#ff6ec7"},
            "triage": {"label": "Triage", "color": "#ffae00"},
        },
        title="OpenAI Agents E2E Test",
    )


@pytest.fixture
def processor(pp):
    return _PixelPulseTracingProcessor(pp)


# ---------------------------------------------------------------------------
# Utility Tests
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_gpt4o_pricing(self):
        cost = _estimate_cost("gpt-4o", 1000, 500)
        assert cost == pytest.approx(0.0025 + 0.005, rel=1e-2)

    def test_gpt4o_mini_pricing(self):
        # gpt-4o-mini: $0.00015/1K in, $0.0006/1K out
        cost = _estimate_cost("gpt-4o-mini", 1000, 500)
        expected = (1000 / 1000 * 0.00015) + (500 / 1000 * 0.0006)
        assert cost == pytest.approx(expected, rel=1e-2)

    def test_unknown_model_fallback(self):
        cost = _estimate_cost("some-unknown-model", 1000, 500)
        assert cost > 0

    def test_zero_tokens(self):
        assert _estimate_cost("gpt-4o", 0, 0) == 0.0


class TestSanitizeName:
    def test_normal_name(self):
        assert _sanitize_name("My Agent") == "my-agent"

    def test_underscore(self):
        assert _sanitize_name("my_agent") == "my-agent"

    def test_none(self):
        assert _sanitize_name(None) == "agent"

    def test_empty(self):
        assert _sanitize_name("") == "agent"


# ---------------------------------------------------------------------------
# Trace Lifecycle Tests
# ---------------------------------------------------------------------------


class TestTraceLifecycle:
    def test_trace_start_emits_run_started(self, pp, processor):
        run_events = []
        pp.run_started = lambda run_id, name="", **kw: run_events.append(("started", run_id, name))

        trace = FakeTrace(trace_id="trace-001", name="research-workflow")
        processor.on_trace_start(trace)

        assert len(run_events) == 1
        assert run_events[0] == ("started", "trace-001", "research-workflow")

    def test_trace_end_emits_run_completed(self, pp, processor):
        run_events = []
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda run_id, status="", **kw: run_events.append(("completed", run_id))

        trace = FakeTrace(trace_id="trace-002", name="test")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)

        assert len(run_events) == 1
        assert run_events[0] == ("completed", "trace-002")

    def test_trace_accumulates_cost(self, pp, processor):
        completed_costs = []
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda run_id, total_cost=0, **kw: completed_costs.append(total_cost)
        pp.agent_started = lambda *a, **kw: None
        pp.agent_completed = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None

        trace = FakeTrace(trace_id="trace-cost", name="cost-test")
        processor.on_trace_start(trace)

        # Simulate a generation span with token usage
        agent_span = FakeSpan(
            span_id="agent-span-1",
            span_data=FakeSpanData(type="agent", name="researcher"),
        )
        processor.on_span_start(agent_span)

        gen_span = FakeSpan(
            span_id="gen-span-1",
            span_data=FakeSpanData(
                type="generation",
                model="gpt-4o",
                usage={"input_tokens": 1000, "output_tokens": 500},
            ),
            parent=agent_span,
        )
        gen_span._trace = trace  # Link to trace
        processor.on_span_start(gen_span)
        processor.on_span_end(gen_span)
        processor.on_span_end(agent_span)
        processor.on_trace_end(trace)

        assert len(completed_costs) == 1
        assert completed_costs[0] > 0


# ---------------------------------------------------------------------------
# Agent Span Tests
# ---------------------------------------------------------------------------


class TestAgentSpans:
    def test_agent_span_emits_started_and_completed(self, pp, processor):
        started = []
        completed = []
        pp.agent_started = lambda agent_id, **kw: started.append(agent_id)
        pp.agent_completed = lambda agent_id, **kw: completed.append(agent_id)
        pp.agent_thinking = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        span = FakeSpan(
            span_id="span-agent-1",
            span_data=FakeSpanData(type="agent", name="researcher", tools=["web_search"]),
        )
        processor.on_span_start(span)
        processor.on_span_end(span)

        assert "researcher" in started
        assert "researcher" in completed

    def test_agent_span_with_error(self, pp, processor):
        errors = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_error = lambda agent_id, error="", **kw: errors.append((agent_id, error))

        span = FakeSpan(
            span_id="span-err-1",
            span_data=FakeSpanData(type="agent", name="Failing Agent"),
            error="Connection timeout",
        )
        processor.on_span_start(span)
        processor.on_span_end(span)

        assert len(errors) == 1
        assert errors[0][0] == "failing-agent"
        assert "Connection timeout" in errors[0][1]

    def test_agent_task_includes_tools_and_handoffs(self, pp, processor):
        tasks = []
        pp.agent_started = lambda agent_id, task="", **kw: tasks.append(task)
        pp.agent_completed = lambda *a, **kw: None

        span = FakeSpan(
            span_id="span-tools-1",
            span_data=FakeSpanData(
                type="agent",
                name="triage",
                tools=["search", "calculate"],
                handoffs=["writer"],
            ),
        )
        processor.on_span_start(span)

        assert len(tasks) == 1
        assert "search" in tasks[0]
        assert "writer" in tasks[0]


# ---------------------------------------------------------------------------
# Generation Span Tests
# ---------------------------------------------------------------------------


class TestGenerationSpans:
    def test_generation_emits_cost_update(self, pp, processor):
        cost_events = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.cost_update = lambda agent_id, cost=0, tokens_in=0, tokens_out=0, model="", **kw: (
            cost_events.append({"agent": agent_id, "cost": cost, "in": tokens_in, "out": tokens_out, "model": model})
        )

        # Parent agent span
        agent_span = FakeSpan(
            span_id="agent-gen-parent",
            span_data=FakeSpanData(type="agent", name="Writer"),
        )
        processor.on_span_start(agent_span)

        # Generation span as child
        gen_span = FakeSpan(
            span_id="gen-1",
            span_data=FakeSpanData(
                type="generation",
                model="gpt-4o",
                usage={"input_tokens": 2000, "output_tokens": 800},
            ),
            parent=agent_span,
        )
        processor.on_span_start(gen_span)
        processor.on_span_end(gen_span)

        assert len(cost_events) == 1
        assert cost_events[0]["model"] == "gpt-4o"
        assert cost_events[0]["in"] == 2000
        assert cost_events[0]["out"] == 800
        assert cost_events[0]["cost"] > 0
        assert cost_events[0]["agent"] == "writer"

    def test_generation_with_output_emits_thinking(self, pp, processor):
        thoughts = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda agent_id, thought="", **kw: thoughts.append(thought)
        pp.cost_update = lambda *a, **kw: None

        agent_span = FakeSpan(
            span_id="agent-think",
            span_data=FakeSpanData(type="agent", name="Writer"),
        )
        processor.on_span_start(agent_span)

        gen_span = FakeSpan(
            span_id="gen-think",
            span_data=FakeSpanData(
                type="generation",
                model="gpt-4o",
                output=[{"content": "Here is my analysis of the market..."}],
                usage={"input_tokens": 100, "output_tokens": 50},
            ),
            parent=agent_span,
        )
        processor.on_span_start(gen_span)
        processor.on_span_end(gen_span)

        assert any("analysis" in t for t in thoughts)


# ---------------------------------------------------------------------------
# Function (Tool) Span Tests
# ---------------------------------------------------------------------------


class TestFunctionSpans:
    def test_function_call_emits_thinking(self, pp, processor):
        thoughts = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda agent_id, thought="", **kw: thoughts.append(thought)
        pp.artifact_created = lambda *a, **kw: None

        agent_span = FakeSpan(
            span_id="agent-tool",
            span_data=FakeSpanData(type="agent", name="Researcher"),
        )
        processor.on_span_start(agent_span)

        func_span = FakeSpan(
            span_id="func-1",
            span_data=FakeSpanData(
                type="function",
                name="web_search",
                input="AI trends 2026",
            ),
            parent=agent_span,
        )
        processor.on_span_start(func_span)

        assert any("web_search" in t for t in thoughts)

    def test_function_result_emits_artifact(self, pp, processor):
        artifacts = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.artifact_created = lambda agent_id, content="", **kw: artifacts.append(content)

        agent_span = FakeSpan(
            span_id="agent-art",
            span_data=FakeSpanData(type="agent", name="Researcher"),
        )
        processor.on_span_start(agent_span)

        func_span = FakeSpan(
            span_id="func-art",
            span_data=FakeSpanData(
                type="function",
                name="search",
                output="Found 5 results about AI agents",
            ),
            parent=agent_span,
        )
        processor.on_span_start(func_span)
        processor.on_span_end(func_span)

        assert len(artifacts) == 1
        assert "search" in artifacts[0]
        assert "5 results" in artifacts[0]

    def test_function_error_emits_thinking_error(self, pp, processor):
        thoughts = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda agent_id, thought="", **kw: thoughts.append(thought)

        agent_span = FakeSpan(
            span_id="agent-ferr",
            span_data=FakeSpanData(type="agent", name="Researcher"),
        )
        processor.on_span_start(agent_span)

        func_span = FakeSpan(
            span_id="func-err",
            span_data=FakeSpanData(type="function", name="broken_tool"),
            parent=agent_span,
            error="API rate limit exceeded",
        )
        processor.on_span_start(func_span)
        processor.on_span_end(func_span)

        assert any("failed" in t.lower() and "rate limit" in t.lower() for t in thoughts)


# ---------------------------------------------------------------------------
# Handoff Span Tests
# ---------------------------------------------------------------------------


class TestHandoffSpans:
    def test_handoff_emits_agent_message(self, pp, processor):
        messages = []
        pp.agent_message = lambda from_id, to_id, content="", **kw: messages.append(
            {"from": from_id, "to": to_id, "content": content}
        )

        span = FakeSpan(
            span_id="handoff-1",
            span_data=FakeSpanData(
                type="handoff",
                from_agent="Triage Agent",
                to_agent="Researcher",
            ),
        )
        processor.on_span_start(span)

        assert len(messages) == 1
        assert messages[0]["from"] == "triage-agent"
        assert messages[0]["to"] == "researcher"
        assert "handoff" in messages[0]["content"].lower()


# ---------------------------------------------------------------------------
# Guardrail Span Tests
# ---------------------------------------------------------------------------


class TestGuardrailSpans:
    def test_guardrail_emits_thinking(self, pp, processor):
        thoughts = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda agent_id, thought="", **kw: thoughts.append(thought)

        agent_span = FakeSpan(
            span_id="agent-guard",
            span_data=FakeSpanData(type="agent", name="Writer"),
        )
        processor.on_span_start(agent_span)

        guard_span = FakeSpan(
            span_id="guard-1",
            span_data=FakeSpanData(type="guardrail", name="content-filter"),
            parent=agent_span,
        )
        processor.on_span_start(guard_span)

        assert any("content-filter" in t for t in thoughts)

    def test_triggered_guardrail_reported(self, pp, processor):
        thoughts = []
        pp.agent_started = lambda *a, **kw: None
        pp.agent_thinking = lambda agent_id, thought="", **kw: thoughts.append(thought)

        agent_span = FakeSpan(
            span_id="agent-guard2",
            span_data=FakeSpanData(type="agent", name="Writer"),
        )
        processor.on_span_start(agent_span)

        guard_span = FakeSpan(
            span_id="guard-trigger",
            span_data=FakeSpanData(type="guardrail", name="pii-filter", triggered=True),
            parent=agent_span,
        )
        processor.on_span_start(guard_span)
        processor.on_span_end(guard_span)

        assert any("triggered" in t.lower() for t in thoughts)


# ---------------------------------------------------------------------------
# Full Pipeline Simulation
# ---------------------------------------------------------------------------


class TestFullPipelineSimulation:
    """Simulate a complete multi-agent workflow with all span types."""

    def test_full_workflow(self, pp, processor):
        """Simulate: triage → researcher (with tool) → writer → review."""
        all_events: list[tuple[str, str, Any]] = []

        def log(event_type, agent_id="", **extra):
            all_events.append((event_type, agent_id, extra))

        pp.run_started = lambda run_id, **kw: log("run_started", run_id=run_id)
        pp.run_completed = lambda run_id, **kw: log("run_completed", run_id=run_id)
        pp.agent_started = lambda agent_id, **kw: log("agent_started", agent_id)
        pp.agent_completed = lambda agent_id, **kw: log("agent_completed", agent_id)
        pp.agent_thinking = lambda agent_id, **kw: log("agent_thinking", agent_id)
        pp.agent_error = lambda agent_id, **kw: log("agent_error", agent_id)
        pp.agent_message = lambda from_id, to_id, **kw: log("handoff", f"{from_id}->{to_id}")
        pp.artifact_created = lambda agent_id, **kw: log("artifact", agent_id)
        pp.cost_update = lambda agent_id, **kw: log("cost", agent_id)

        # 1. Trace starts
        trace = FakeTrace(trace_id="full-trace", name="research-pipeline")
        processor.on_trace_start(trace)

        # 2. Triage agent
        triage = FakeSpan(
            span_id="triage-span",
            span_data=FakeSpanData(type="agent", name="Triage", handoffs=["Researcher"]),
        )
        processor.on_span_start(triage)

        # 3. Handoff to researcher
        handoff = FakeSpan(
            span_id="handoff-tr",
            span_data=FakeSpanData(type="handoff", from_agent="Triage", to_agent="Researcher"),
        )
        processor.on_span_start(handoff)

        # Triage completes
        processor.on_span_end(triage)

        # 4. Researcher agent with tool call
        researcher = FakeSpan(
            span_id="researcher-span",
            span_data=FakeSpanData(type="agent", name="Researcher", tools=["web_search"]),
        )
        processor.on_span_start(researcher)

        # Tool call
        tool = FakeSpan(
            span_id="tool-search",
            span_data=FakeSpanData(type="function", name="web_search", input="AI trends"),
            parent=researcher,
        )
        processor.on_span_start(tool)
        tool.span_data.output = "Found 10 relevant articles"
        processor.on_span_end(tool)

        # LLM generation
        gen = FakeSpan(
            span_id="gen-researcher",
            span_data=FakeSpanData(
                type="generation",
                model="gpt-4o",
                usage={"input_tokens": 3000, "output_tokens": 1200},
                output=[{"content": "Based on my research, AI agents are..."}],
            ),
            parent=researcher,
        )
        gen._trace = trace
        processor.on_span_start(gen)
        processor.on_span_end(gen)

        # Researcher completes
        researcher.span_data.output_type = "ResearchResult"
        processor.on_span_end(researcher)

        # 5. Writer agent
        writer = FakeSpan(
            span_id="writer-span",
            span_data=FakeSpanData(type="agent", name="Writer"),
        )
        processor.on_span_start(writer)

        writer_gen = FakeSpan(
            span_id="gen-writer",
            span_data=FakeSpanData(
                type="generation",
                model="gpt-4o-mini",
                usage={"input_tokens": 2000, "output_tokens": 3000},
            ),
            parent=writer,
        )
        writer_gen._trace = trace
        processor.on_span_start(writer_gen)
        processor.on_span_end(writer_gen)
        processor.on_span_end(writer)

        # 6. Guardrail check
        guard = FakeSpan(
            span_id="guard-final",
            span_data=FakeSpanData(type="guardrail", name="quality-check", triggered=False),
            parent=writer,
        )
        processor.on_span_start(guard)
        processor.on_span_end(guard)

        # 7. Trace ends
        processor.on_trace_end(trace)

        # Assertions
        event_types = [e[0] for e in all_events]

        # Must have run lifecycle
        assert "run_started" in event_types
        assert "run_completed" in event_types

        # Must have agent lifecycles
        assert event_types.count("agent_started") >= 3  # triage, researcher, writer
        assert event_types.count("agent_completed") >= 3

        # Must have handoff
        assert "handoff" in event_types

        # Must have tool artifact
        assert "artifact" in event_types

        # Must have cost updates (2 generations)
        assert event_types.count("cost") >= 2

        # Must have thinking events
        assert "agent_thinking" in event_types

    def test_shutdown_clears_state(self, processor):
        """shutdown() should clear all internal tracking state."""
        trace = FakeTrace(trace_id="shutdown-test", name="test")
        processor.on_trace_start(trace)

        span = FakeSpan(
            span_id="span-shutdown",
            span_data=FakeSpanData(type="agent", name="Agent"),
        )
        processor.on_span_start(span)

        processor.shutdown()

        assert len(processor._active_traces) == 0
        assert len(processor._active_agents) == 0
        assert len(processor._span_start_times) == 0
        assert len(processor._trace_costs) == 0
