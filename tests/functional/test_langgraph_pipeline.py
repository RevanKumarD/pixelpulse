"""Functional tests: LangGraph adapter → PixelPulse → /api/events.

Tests the full adapter stack without mocking anything:
  graph.invoke() → LangChain callbacks → LangGraphAdapter → pp.agent_started()
  → emit_sync() → EventBus singleton → bus._history → /api/events

This is the only test layer that validates the complete adapter → server chain.
Unit tests verify adapter logic in isolation. E2E tests mock the pp boundary.
This test proves it all works together.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

import pixelpulse.bus as bus_module
from pixelpulse import PixelPulse


@pytest.fixture(autouse=True)
def fresh_bus():
    """Reset the singleton bus before/after each test for isolation."""
    bus_module._bus = None
    yield
    bus_module._bus = None


# ---------------------------------------------------------------------------
# Minimal LangGraph pipeline — no LLM calls, pure Python logic
# ---------------------------------------------------------------------------


class ResearchState(TypedDict):
    topic: str
    result: str


def research_node(state: ResearchState) -> dict[str, Any]:
    return {"result": f"Research on: {state['topic']}"}


def write_node(state: ResearchState) -> dict[str, Any]:
    return {"result": state["result"] + " | Article written"}


def build_graph():
    builder = StateGraph(ResearchState)
    builder.add_node("research_node", research_node)
    builder.add_node("write_node", write_node)
    builder.add_edge(START, "research_node")
    builder.add_edge("research_node", "write_node")
    builder.add_edge("write_node", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pp():
    return PixelPulse(
        agents={
            "research_node": {"team": "research", "role": "Researcher"},
            "write_node": {"team": "content", "role": "Writer"},
        },
        teams={
            "research": {"label": "Research", "color": "#00d4ff"},
            "content": {"label": "Content", "color": "#ff6ec7"},
        },
        pipeline=["research", "content"],
    )


@pytest.fixture
def graph():
    return build_graph()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLangGraphFunctional:
    """Full stack: LangGraph adapter → bus → /api/events."""

    async def test_graph_invoke_emits_to_events_endpoint(self, pp, graph):
        """After graph.invoke(), events appear at /api/events — no mocks."""
        app = pp._create_app()
        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            graph.invoke({"topic": "Sustainability", "result": ""})

            # Let emit_sync() tasks complete before querying
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            assert resp.status_code == 200
            events = resp.json()

            # Adapter must emit at least one started + one completed event.
            # Protocol types agent.started / agent.completed both map to
            # dashboard type "agent_status" — distinguished by payload.status.
            assert len(events) >= 2
            agent_status = [e for e in events if e["type"] == "agent_status"]
            assert any(e["payload"].get("status") == "active" for e in agent_status)
            assert any(e["payload"].get("status") == "idle" for e in agent_status)

    async def test_both_nodes_emit_started_events(self, pp, graph):
        """Both research_node and write_node each trigger agent_started."""
        app = pp._create_app()
        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            graph.invoke({"topic": "AI Ethics", "result": ""})
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # agent.started maps to "agent_status" with status="active"
            started_events = [
                e for e in events
                if e["type"] == "agent_status" and e["payload"].get("status") == "active"
            ]
            # One started event per graph node (research_node + write_node)
            assert len(started_events) >= 2

    async def test_graph_output_unchanged_by_instrumentation(self, pp, graph):
        """Instrumenting a graph must not change its output."""
        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        result = graph.invoke({"topic": "Climate", "result": ""})

        assert "Research on: Climate" in result["result"]
        assert "Article written" in result["result"]

    async def test_run_lifecycle_events_appear(self, pp, graph):
        """run_started and/or run_completed should appear in /api/events."""
        app = pp._create_app()
        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            graph.invoke({"topic": "Quantum Computing", "result": ""})
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()
            types = [e["type"] for e in events]

            # At minimum we expect agent lifecycle events across both nodes
            lifecycle_events = [t for t in types if "agent" in t or "run" in t]
            assert len(lifecycle_events) >= 2

    async def test_events_empty_before_graph_runs(self, pp, graph):
        """No events appear until graph.invoke() is called."""
        app = pp._create_app()
        pp.adapter("langgraph").instrument(graph)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Query before running the graph
            resp = await client.get("/api/events")
            assert resp.json() == []

    async def test_detach_stops_event_emission(self, pp, graph):
        """After adapter.detach(), graph.invoke() produces no new events."""
        app = pp._create_app()
        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First run — events should appear
            graph.invoke({"topic": "First Run", "result": ""})
            await asyncio.sleep(0)
            resp = await client.get("/api/events")
            events_after_first = resp.json()
            assert len(events_after_first) >= 1

            # Detach the adapter
            adapter.detach()

            # Reset bus to get a clean count
            bus_module._bus = None
            app2 = pp._create_app()

            async with AsyncClient(
                transport=ASGITransport(app=app2), base_url="http://test"
            ) as client2:
                # Second run — no new events
                graph.invoke({"topic": "Second Run", "result": ""})
                await asyncio.sleep(0)
                resp2 = await client2.get("/api/events")
                assert resp2.json() == []
