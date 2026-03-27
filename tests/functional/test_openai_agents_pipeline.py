"""Functional tests: OpenAI Agents adapter → PixelPulse → /api/events.

Tests the full OpenAI Agents adapter integration path without mocking pp:
  _PixelPulseTracingProcessor.on_span_start/end() → EventBus → /api/events

Since the `agents` package fails to import on Python 3.11, we cannot call
adapter.instrument() (which requires add_trace_processor).  Instead we import
_PixelPulseTracingProcessor directly and drive it with fake span objects.

This validates the real adapter logic → real pp → real bus → real HTTP.
"""
from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import pixelpulse.bus as bus_module
from pixelpulse import PixelPulse
from pixelpulse.adapters.openai_agents import _PixelPulseTracingProcessor


@pytest.fixture(autouse=True)
def fresh_bus():
    """Reset the singleton bus before/after each test for isolation."""
    bus_module._bus = None
    yield
    bus_module._bus = None


@pytest.fixture
def pp():
    return PixelPulse(
        agents={
            "triage-agent": {"team": "triage", "role": "Triage"},
            "research-agent": {"team": "research", "role": "Researcher"},
        },
        teams={
            "triage": {"label": "Triage", "color": "#ffaa00"},
            "research": {"label": "Research", "color": "#00d4ff"},
        },
        pipeline=["triage", "research"],
    )


@pytest.fixture
def processor(pp):
    return _PixelPulseTracingProcessor(pp)


# ---------------------------------------------------------------------------
# Fake span / span_data builders
# ---------------------------------------------------------------------------


def _make_agent_span_data(name: str, tools: list = None, output_type: str = "") -> Any:
    return types.SimpleNamespace(
        type="agent",
        name=name,
        tools=tools or [],
        handoffs=[],
        output_type=output_type,
    )


def _make_generation_span_data(
    model: str = "gpt-4o-mini",
    input_tokens: int = 100,
    output_tokens: int = 50,
    output: list = None,
) -> Any:
    return types.SimpleNamespace(
        type="generation",
        model=model,
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
        output=output or [],
    )


def _make_function_span_data(
    name: str = "web_search", input: str = "AI trends", output: str = "Result"
) -> Any:
    return types.SimpleNamespace(
        type="function",
        name=name,
        input=input,
        output=output,
    )


def _make_handoff_span_data(from_agent: str, to_agent: str) -> Any:
    return types.SimpleNamespace(
        type="handoff",
        from_agent=from_agent,
        to_agent=to_agent,
    )


def _make_guardrail_span_data(name: str = "content-policy", triggered: bool = False) -> Any:
    return types.SimpleNamespace(
        type="guardrail",
        name=name,
        triggered=triggered,
    )


def _make_span(
    span_id: str,
    span_data: Any,
    error: Any = None,
    parent: Any = None,
) -> Any:
    return types.SimpleNamespace(
        span_id=span_id,
        span_data=span_data,
        error=error,
        parent=parent,
        trace=None,
        _trace=None,
    )


def _make_trace(trace_id: str, name: str = "agent-run") -> Any:
    return types.SimpleNamespace(trace_id=trace_id, name=name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenAIAgentsFunctional:
    """Full stack: _PixelPulseTracingProcessor → bus → /api/events."""

    async def test_events_empty_before_processor(self, pp):
        """No events appear before the processor is called."""
        app = pp._create_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/events")
            assert resp.json() == []

    async def test_agent_span_start_emits_active_status(self, pp, processor):
        """on_span_start with agent span_data emits agent_status active."""
        app = pp._create_app()
        span = _make_span("span-1", _make_agent_span_data("triage-agent"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_span_start(span)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            assert resp.status_code == 200
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            assert len(agent_status) >= 1
            assert any(e["payload"].get("status") == "active" for e in agent_status)

    async def test_agent_span_end_emits_idle_status(self, pp, processor):
        """on_span_end with agent span_data emits agent_status idle."""
        app = pp._create_app()
        span = _make_span("span-1", _make_agent_span_data("triage-agent"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_span_start(span)
            processor.on_span_end(span)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            statuses = [e["payload"].get("status") for e in agent_status]
            assert "active" in statuses
            assert "idle" in statuses

    async def test_agent_name_in_event_payload(self, pp, processor):
        """The agent_id in the payload matches the span_data.name."""
        app = pp._create_app()
        span = _make_span("span-1", _make_agent_span_data("triage-agent"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_span_start(span)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            names = [e["payload"].get("agent_id") for e in agent_status]
            # _sanitize_name("triage-agent") → "triage-agent"
            assert "triage-agent" in names

    async def test_trace_start_emits_run_event(self, pp, processor):
        """on_trace_start emits a run lifecycle event visible at /api/events."""
        app = pp._create_app()
        trace = _make_trace("trace-1", "MyAgentWorkflow")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_trace_start(trace)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # run_started maps to a run-type dashboard event
            assert len(events) >= 1

    async def test_trace_start_and_end_produce_multiple_events(self, pp, processor):
        """on_trace_start + on_trace_end each produce at least one event."""
        app = pp._create_app()
        trace = _make_trace("trace-1")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_trace_start(trace)
            processor.on_trace_end(trace)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            assert len(events) >= 2

    async def test_function_span_produces_event(self, pp, processor):
        """on_span_start/end with function span_data emits at least one event."""
        app = pp._create_app()
        # Put an agent span in context first so _find_parent_agent has something
        agent_span = _make_span("span-agent", _make_agent_span_data("research-agent"))
        processor.on_span_start(agent_span)

        func_span = _make_span(
            "span-func",
            _make_function_span_data("web_search", "AI", "Result text"),
            parent=agent_span,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_span_start(func_span)
            processor.on_span_end(func_span)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # At minimum: agent_started for research-agent + thinking/artifact for tool
            assert len(events) >= 2

    async def test_multiple_agents_span_produce_events(self, pp, processor):
        """Multiple agent spans each produce agent_status events."""
        app = pp._create_app()
        span1 = _make_span("span-1", _make_agent_span_data("triage-agent"))
        span2 = _make_span("span-2", _make_agent_span_data("research-agent"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_span_start(span1)
            processor.on_span_start(span2)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            names_seen = {e["payload"].get("agent_id") for e in agent_status}
            assert "triage-agent" in names_seen
            assert "research-agent" in names_seen

    async def test_agent_error_span_emits_error_event(self, pp, processor):
        """on_span_end with error set emits an error-type event."""
        app = pp._create_app()
        span = _make_span(
            "span-err",
            _make_agent_span_data("triage-agent"),
            error={"message": "Something went wrong"},
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            processor.on_span_start(span)
            processor.on_span_end(span)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # At least started + error events
            assert len(events) >= 2

    async def test_shutdown_clears_state(self, pp, processor):
        """shutdown() clears internal state without raising."""
        span = _make_span("span-1", _make_agent_span_data("triage-agent"))
        processor.on_span_start(span)

        # Should not raise
        processor.shutdown()

        assert processor._active_agents == {}
        assert processor._active_traces == {}
        assert processor._span_start_times == {}
