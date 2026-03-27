"""Integration tests: prove pp.emit() → EventBus singleton → /api/events.

Unit tests mock pp. Server tests use an isolated bus. THIS test proves
the real chain works: PixelPulse event methods → emit_sync() → singleton
bus → /api/events HTTP response.

Why this matters: emit_sync() silently drops events if no event loop is
running. These tests verify the path works in a real async context.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import pixelpulse.bus as bus_module
from pixelpulse import PixelPulse


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
            "researcher": {"team": "research", "role": "Analyst"},
            "writer": {"team": "content", "role": "Writer"},
        },
        teams={
            "research": {"label": "Research Lab", "color": "#00d4ff"},
            "content": {"label": "Content Studio", "color": "#ff6ec7"},
        },
        pipeline=["research", "content"],
    )


class TestEventPipelineWiring:
    """The critical wiring test: pp public API → bus._history → HTTP endpoint."""

    async def test_agent_started_appears_in_events(self, pp):
        """agent_started() emits to the bus; /api/events reflects it.

        Protocol event type "agent.started" maps to dashboard type "agent_status"
        with payload.status = "active".
        """
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            pp.agent_started("researcher", task="Investigating markets")
            await asyncio.sleep(0)  # let loop.create_task(bus.emit(...)) execute

            resp = await client.get("/api/events")
            assert resp.status_code == 200
            events = resp.json()

            assert len(events) >= 1
            # agent.started maps to dashboard type "agent_status" with status="active"
            agent_status_events = [e for e in events if e["type"] == "agent_status"]
            assert any(
                e["payload"].get("status") == "active" for e in agent_status_events
            )

    async def test_agent_completed_appears_in_events(self, pp):
        """agent_completed() is retrievable via /api/events.

        Protocol event type "agent.completed" maps to dashboard type "agent_status"
        with payload.status = "idle".
        """
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            pp.agent_completed("researcher", output="Found 5 key trends")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status_events = [e for e in events if e["type"] == "agent_status"]
            assert any(
                e["payload"].get("status") == "idle" for e in agent_status_events
            )

    async def test_multiple_events_retain_emission_order(self, pp):
        """Events appear in the order they were emitted."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            pp.agent_started("researcher", task="Phase 1")
            pp.agent_thinking("researcher", thought="Analyzing data")
            pp.agent_completed("researcher", output="Done")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            assert len(events) >= 3
            # All three map to "agent_status"; order is preserved in bus history
            # First event should be status=active (started), last should be status=idle (completed)
            agent_status_events = [e for e in events if e["type"] == "agent_status"]
            assert agent_status_events[0]["payload"].get("status") == "active"
            assert agent_status_events[-1]["payload"].get("status") == "idle"

    async def test_agent_message_appears_in_events(self, pp):
        """agent_message() creates a message_flow event at /api/events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            pp.agent_message("researcher", "writer", content="Here is the data", tag="handoff")
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # message.sent maps to dashboard type "message_flow"
            types = [e["type"] for e in events]
            assert "message_flow" in types

    async def test_cost_update_appears_in_events(self, pp):
        """cost_update() is stored in the bus and visible via /api/events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            pp.cost_update(
                "researcher", cost=0.0042, tokens_in=1200, tokens_out=400, model="gpt-4o-mini"
            )
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # cost.update maps to dashboard type "cost_update"
            types = [e["type"] for e in events]
            assert "cost_update" in types

    async def test_ingest_endpoint_wires_to_history(self, pp):
        """/api/events/ingest directly writes to the bus; visible at /api/events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/events/ingest",
                json={
                    "type": "agent.started",
                    "payload": {"agent_id": "writer", "task": "Writing article"},
                },
            )

            resp = await client.get("/api/events")
            events = resp.json()

            assert len(events) >= 1

    async def test_events_endpoint_empty_before_any_emission(self, pp):
        """/api/events is empty when no events have been emitted."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/events")
            assert resp.status_code == 200
            assert resp.json() == []

    async def test_full_agent_lifecycle_wired(self, pp):
        """started → thinking → completed lifecycle all appear at /api/events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            pp.agent_started("researcher", task="Full lifecycle test")
            pp.agent_thinking("researcher", thought="Considering approach...")
            pp.agent_completed("researcher", output="Lifecycle complete")
            pp.cost_update("researcher", cost=0.001, tokens_in=500, tokens_out=100)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # 4 emits → 4 dashboard events (3 agent_status + 1 cost_update)
            assert len(events) >= 4
            types = [e["type"] for e in events]
            assert "agent_status" in types
            assert "cost_update" in types
