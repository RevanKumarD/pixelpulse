"""Tests for the OpenAI Agents SDK adapter.

Uses mocks for all openai-agents imports so tests work without installing the SDK.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch
import pytest

from pixelpulse.adapters.openai_agents import (
    OpenAIAgentsAdapter,
    _PixelPulseTracingProcessor,
    _estimate_cost,
    _sanitize_name,
)


@pytest.fixture
def mock_pp():
    """Create a mock PixelPulse instance."""
    pp = MagicMock()
    pp.agent_started = MagicMock()
    pp.agent_completed = MagicMock()
    pp.agent_error = MagicMock()
    pp.agent_thinking = MagicMock()
    pp.agent_message = MagicMock()
    pp.cost_update = MagicMock()
    pp.run_started = MagicMock()
    pp.run_completed = MagicMock()
    pp.artifact_created = MagicMock()
    pp.stage_entered = MagicMock()
    pp.stage_exited = MagicMock()
    return pp


@pytest.fixture
def processor(mock_pp):
    return _PixelPulseTracingProcessor(mock_pp)


def _make_span(span_type, span_id="span-1", error=None, **data_attrs):
    """Create a mock span with span_data of the given type."""
    span_data = MagicMock()
    span_data.type = span_type
    for k, v in data_attrs.items():
        setattr(span_data, k, v)

    span = MagicMock()
    span.span_id = span_id
    span.span_data = span_data
    span.error = error
    span.parent = None
    span.trace = None
    return span


def _make_trace(trace_id="trace-1", name="test-trace"):
    trace = MagicMock()
    trace.trace_id = trace_id
    trace.name = name
    return trace


# ── Trace lifecycle ──

class TestTraceLifecycle:
    def test_trace_start_emits_run_started(self, processor, mock_pp):
        trace = _make_trace("t-001", "My Workflow")
        processor.on_trace_start(trace)
        mock_pp.run_started.assert_called_once_with("t-001", name="My Workflow")

    def test_trace_end_emits_run_completed(self, processor, mock_pp):
        trace = _make_trace("t-001", "My Workflow")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        mock_pp.run_completed.assert_called_once_with(
            "t-001", status="completed", total_cost=0.0
        )

    def test_trace_end_accumulates_cost(self, processor, mock_pp):
        trace = _make_trace("t-001")
        processor.on_trace_start(trace)

        # Simulate a generation span with token usage
        agent_span = _make_span("agent", span_id="s-agent", name="my-agent")
        processor.on_span_start(agent_span)

        gen_span = _make_span(
            "generation", span_id="s-gen",
            model="gpt-4.1-mini",
            usage={"input_tokens": 1000, "output_tokens": 500},
            output=None,
        )
        gen_span.parent = agent_span
        gen_span.trace = trace
        processor.on_span_end(gen_span)

        # Cost should be accumulated
        processor.on_trace_end(trace)
        call_args = mock_pp.run_completed.call_args
        assert call_args[1]["total_cost"] > 0 or call_args[0][2] > 0


# ── Agent spans ──

class TestAgentSpans:
    def test_agent_start_emits_agent_started(self, processor, mock_pp):
        span = _make_span(
            "agent", span_id="s-1",
            name="Research Agent",
            tools=["web_search", "calculator"],
            handoffs=["Writer Agent"],
            output_type="str",
        )
        processor.on_span_start(span)
        mock_pp.agent_started.assert_called_once()
        call_args = mock_pp.agent_started.call_args
        assert call_args[0][0] == "research-agent"
        assert "web_search" in call_args[1]["task"]

    def test_agent_end_emits_agent_completed(self, processor, mock_pp):
        span = _make_span("agent", span_id="s-1", name="My Agent", output_type="str")
        processor.on_span_start(span)
        processor.on_span_end(span)
        mock_pp.agent_completed.assert_called_once()
        assert mock_pp.agent_completed.call_args[0][0] == "my-agent"

    def test_agent_error_emits_agent_error(self, processor, mock_pp):
        span = _make_span(
            "agent", span_id="s-1", name="Bad Agent",
            output_type=None,
        )
        span.error = "Something went wrong"
        processor.on_span_start(span)
        processor.on_span_end(span)
        mock_pp.agent_error.assert_called_once_with(
            "bad-agent", error="Something went wrong"
        )


# ── Generation spans ──

class TestGenerationSpans:
    def test_generation_emits_cost_update(self, processor, mock_pp):
        # Need an active agent for context
        agent_span = _make_span("agent", span_id="s-agent", name="writer")
        processor.on_span_start(agent_span)

        gen_span = _make_span(
            "generation", span_id="s-gen",
            model="gpt-4.1",
            usage={"input_tokens": 2000, "output_tokens": 500},
            output=[{"content": "Hello world"}],
        )
        gen_span.parent = agent_span
        processor.on_span_end(gen_span)

        mock_pp.cost_update.assert_called_once()
        call_args = mock_pp.cost_update.call_args
        assert call_args[1]["tokens_in"] == 2000
        assert call_args[1]["tokens_out"] == 500
        assert call_args[1]["model"] == "gpt-4.1"
        assert call_args[1]["cost"] > 0

    def test_generation_emits_thinking_with_output(self, processor, mock_pp):
        agent_span = _make_span("agent", span_id="s-agent", name="writer")
        processor.on_span_start(agent_span)

        gen_span = _make_span(
            "generation", span_id="s-gen",
            model="gpt-4.1",
            usage={"input_tokens": 100, "output_tokens": 50},
            output=[{"content": "The answer is 42"}],
        )
        gen_span.parent = agent_span
        processor.on_span_end(gen_span)

        # Should emit thinking with the model output
        mock_pp.agent_thinking.assert_called()
        thought = mock_pp.agent_thinking.call_args[1]["thought"]
        assert "42" in thought


# ── Function spans ──

class TestFunctionSpans:
    def test_function_start_emits_thinking(self, processor, mock_pp):
        agent_span = _make_span("agent", span_id="s-agent", name="coder")
        processor.on_span_start(agent_span)

        func_span = _make_span(
            "function", span_id="s-func",
            name="web_search", input="python tutorials", output=None,
        )
        func_span.parent = agent_span
        processor.on_span_start(func_span)

        mock_pp.agent_thinking.assert_called()
        thought = mock_pp.agent_thinking.call_args[1]["thought"]
        assert "web_search" in thought

    def test_function_end_emits_artifact(self, processor, mock_pp):
        agent_span = _make_span("agent", span_id="s-agent", name="coder")
        processor.on_span_start(agent_span)

        func_span = _make_span(
            "function", span_id="s-func",
            name="calculator", input="2+2", output="4",
        )
        func_span.parent = agent_span
        processor.on_span_end(func_span)

        mock_pp.artifact_created.assert_called_once()
        assert "calculator" in mock_pp.artifact_created.call_args[1]["content"]


# ── Handoff spans ──

class TestHandoffSpans:
    def test_handoff_emits_agent_message(self, processor, mock_pp):
        span = _make_span(
            "handoff", span_id="s-h1",
            from_agent="Triage Agent", to_agent="Research Agent",
        )
        processor.on_span_start(span)

        mock_pp.agent_message.assert_called_once()
        call_args = mock_pp.agent_message.call_args
        assert call_args[0][0] == "triage-agent"
        assert call_args[0][1] == "research-agent"
        assert call_args[1]["tag"] == "handoff"


# ── Utility functions ──

class TestUtilities:
    def test_sanitize_name(self):
        assert _sanitize_name("Research Agent") == "research-agent"
        assert _sanitize_name("my_tool") == "my-tool"
        assert _sanitize_name(None) == "agent"
        assert _sanitize_name("") == "agent"

    def test_estimate_cost_known_model(self):
        cost = _estimate_cost("gpt-4.1-mini", 1000, 500)
        assert cost > 0
        assert cost < 0.01  # Should be cheap for mini

    def test_estimate_cost_unknown_model(self):
        cost = _estimate_cost("custom-model", 1000, 500)
        assert cost > 0

    def test_shutdown_clears_state(self, processor):
        trace = _make_trace()
        processor.on_trace_start(trace)
        span = _make_span("agent", name="test")
        processor.on_span_start(span)

        processor.shutdown()
        assert len(processor._active_traces) == 0
        assert len(processor._active_agents) == 0


# ── Adapter integration ──

class TestAdapterIntegration:
    def test_adapter_creation(self, mock_pp):
        adapter = OpenAIAgentsAdapter(mock_pp)
        assert adapter._processor is None
        assert not adapter._installed

    @patch("pixelpulse.adapters.openai_agents.logger")
    def test_adapter_instrument_without_sdk(self, mock_logger, mock_pp):
        """Should log error when openai-agents is not installed."""
        adapter = OpenAIAgentsAdapter(mock_pp)
        # Force the import to fail regardless of whether the SDK is installed
        with patch.dict(sys.modules, {"agents": None, "agents.tracing": None}):
            adapter.instrument()
        mock_logger.error.assert_called_once()
        assert not adapter._installed

    def test_adapter_detach(self, mock_pp):
        adapter = OpenAIAgentsAdapter(mock_pp)
        adapter._processor = MagicMock()
        adapter._installed = True
        adapter.detach()
        assert adapter._processor is None
        assert not adapter._installed
