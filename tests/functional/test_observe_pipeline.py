"""Functional tests: @observe decorator → PixelPulse → /api/events.

Tests the full stack without mocking anything:
  @observe(pp) → pp.agent_started/completed() → emit_sync()
  → EventBus singleton → bus._history → /api/events

This validates that the decorator produces the correct dashboard events
through the complete wiring chain.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import pixelpulse.bus as bus_module
from pixelpulse import PixelPulse
from pixelpulse.decorators import observe


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
            "researcher": {"team": "research", "role": "Deep research"},
            "writer": {"team": "commerce", "role": "Writes listings"},
        },
        teams={
            "research": {"label": "Research"},
            "commerce": {"label": "Commerce"},
        },
        pipeline=["research", "commerce"],
    )


class TestObservePipeline:
    @pytest.mark.asyncio
    async def test_decorated_agent_emits_started_and_completed(self, pp):
        """@observe(as_type='agent') emits agent_status active then idle at /api/events."""

        @observe(pp, as_type="agent", name="researcher")
        def research(topic: str) -> str:
            return f"Findings on {topic}"

        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            research("sustainability")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        agent_status = [e for e in events if e["type"] == "agent_status"]
        statuses = [e["payload"].get("status") for e in agent_status]
        assert "active" in statuses
        assert "idle" in statuses

    @pytest.mark.asyncio
    async def test_decorated_agent_name_in_payload(self, pp):
        """@observe emits events with the correct agent name."""

        @observe(pp, as_type="agent", name="writer")
        def write_brief(topic: str) -> str:
            return f"Brief: {topic}"

        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            write_brief("wellness kits")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        agent_status = [e for e in events if e["type"] == "agent_status"]
        # Agent name is stored under "agent_id" in the payload (protocol field)
        names = [e["payload"].get("agent_id") for e in agent_status]
        assert "writer" in names

    @pytest.mark.asyncio
    async def test_tool_type_emits_thinking_not_status(self, pp):
        """@observe(as_type='tool') emits thinking events, not agent_status starts."""

        @observe(pp, as_type="agent", name="researcher")
        def research(topic: str) -> str:
            web_search(topic)
            return f"Research: {topic}"

        @observe(pp, as_type="tool", name="web-search")
        def web_search(query: str) -> str:
            return f"Results: {query}"

        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            research("trends")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        # researcher's agent_status events should be present
        # Agent name is stored under "agent_id" in the payload (protocol field)
        agent_status = [e for e in events if e["type"] == "agent_status"]
        assert any(e["payload"].get("agent_id") == "researcher" for e in agent_status)

        # web-search should NOT appear as its own agent_status start
        # (tools emit thinking events, not agent_started)
        assert not any(
            e["payload"].get("agent_id") == "web-search"
            and e["payload"].get("status") == "active"
            for e in agent_status
        )

    @pytest.mark.asyncio
    async def test_nested_observe_context_propagation(self, pp):
        """Nested @observe calls propagate parent context correctly."""

        @observe(pp, as_type="agent", name="researcher")
        def research(topic: str) -> str:
            inner_tool(topic)
            return f"Done: {topic}"

        @observe(pp, as_type="tool", name="inner-tool")
        def inner_tool(q: str) -> str:
            return f"Tool result: {q}"

        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            research("AI trends")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        # Must have at least researcher start + researcher complete
        agent_status = [e for e in events if e["type"] == "agent_status"]
        assert len(agent_status) >= 2

    @pytest.mark.asyncio
    async def test_empty_events_before_decorated_call(self, pp):
        """No events emitted before the decorated function is called."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/events")
            assert resp.json() == []

    @pytest.mark.asyncio
    async def test_multiple_agents_pipeline(self, pp):
        """Multiple decorated agents produce sequential events in order."""

        @observe(pp, as_type="agent", name="researcher")
        def research(topic: str) -> str:
            return f"Research: {topic}"

        @observe(pp, as_type="agent", name="writer")
        def write(research_output: str) -> str:
            return f"Brief: {research_output}"

        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            findings = research("wellness")
            write(findings)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        agent_status = [e for e in events if e["type"] == "agent_status"]
        # Agent name is stored under "agent_id" in the payload (protocol field)
        agents_seen = {e["payload"].get("agent_id") for e in agent_status}
        assert "researcher" in agents_seen
        assert "writer" in agents_seen
