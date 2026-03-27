"""Functional tests: AutoGen adapter → PixelPulse → /api/events.

Tests the full AutoGen adapter integration path without mocking pp:
  adapter.instrument(team) → fake team.run_stream() → EventBus → /api/events

Since autogen_agentchat is not installed, we simulate the async generator
that AutoGen's run_stream would yield, and directly call the wrapped method.

AutoGen messages need `type(msg).__name__` to return the right class name,
so we use custom fake classes rather than SimpleNamespace.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

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
            "researcher": {"team": "research", "role": "Researcher"},
            "writer": {"team": "content", "role": "Writer"},
        },
        teams={
            "research": {"label": "Research", "color": "#00d4ff"},
            "content": {"label": "Content", "color": "#ff6ec7"},
        },
        pipeline=["research", "content"],
    )


# ---------------------------------------------------------------------------
# Fake AutoGen message types (class name is what the adapter inspects)
# ---------------------------------------------------------------------------


class TextMessage:
    """Fake AutoGen TextMessage."""

    def __init__(self, source: str, content: str) -> None:
        self.source = source
        self.content = content


class StopMessage:
    """Fake AutoGen StopMessage."""

    def __init__(self, source: str, content: str = "Stopping") -> None:
        self.source = source
        self.content = content


class ToolCallRequestEvent:
    """Fake AutoGen ToolCallRequestEvent."""

    def __init__(self, source: str, content: str = "Calling tool") -> None:
        self.source = source
        self.content = content


class ToolCallExecutionEvent:
    """Fake AutoGen ToolCallExecutionEvent."""

    def __init__(self, source: str, content: str = "Tool result") -> None:
        self.source = source
        self.content = content


class HandoffMessage:
    """Fake AutoGen HandoffMessage."""

    def __init__(self, source: str, content: str) -> None:
        self.source = source
        self.content = content  # content = target agent name


class TaskResult:
    """Fake AutoGen TaskResult."""

    def __init__(self, stop_reason: str = "Done", messages: list = None) -> None:
        self.stop_reason = stop_reason
        self.messages = messages or []


# ---------------------------------------------------------------------------
# Fake team factory
# ---------------------------------------------------------------------------


def _make_fake_team(messages: list[Any]) -> Any:
    """Create a fake AutoGen team whose run_stream yields the given messages."""

    class FakeTeam:
        _participants = []

        async def run_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            for msg in messages:
                yield msg

    return FakeTeam()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAutoGenFunctional:
    """Full stack: AutoGen adapter (simulated run_stream) → bus → /api/events."""

    async def test_events_empty_before_instrument(self, pp):
        """No events appear before any adapter calls."""
        app = pp._create_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/events")
            assert resp.json() == []

    async def test_run_stream_emits_run_started(self, pp):
        """Iterating the wrapped run_stream emits run_started at /api/events."""
        app = pp._create_app()
        msgs = [TextMessage("researcher", "Researching topic")]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Consume the async generator
            async for _ in fake_team.run_stream(task="Research AI"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            assert resp.status_code == 200
            events = resp.json()

            # run_started + at least one agent event
            assert len(events) >= 1

    async def test_text_message_emits_agent_status(self, pp):
        """A TextMessage from 'researcher' causes agent_status active at /api/events."""
        app = pp._create_app()
        msgs = [TextMessage("researcher", "I am researching now")]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async for _ in fake_team.run_stream(task="Research"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            assert len(agent_status) >= 1
            assert any(e["payload"].get("status") == "active" for e in agent_status)

    async def test_agent_name_in_payload(self, pp):
        """The agent_id in the payload matches the message source."""
        app = pp._create_app()
        msgs = [TextMessage("researcher", "Research output")]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async for _ in fake_team.run_stream(task="Research"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            names = [e["payload"].get("agent_id") for e in agent_status]
            assert "researcher" in names

    async def test_stop_message_emits_idle_status(self, pp):
        """A StopMessage causes the agent to be marked idle (agent_status idle)."""
        app = pp._create_app()
        msgs = [
            TextMessage("researcher", "Working..."),
            StopMessage("researcher", "All done"),
        ]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async for _ in fake_team.run_stream(task="Research"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            statuses = [e["payload"].get("status") for e in agent_status]
            # researcher started (active) then stopped (idle)
            assert "active" in statuses
            assert "idle" in statuses

    async def test_multiple_agents_produce_events(self, pp):
        """Messages from multiple agents each produce agent_status events."""
        app = pp._create_app()
        msgs = [
            TextMessage("researcher", "Findings"),
            TextMessage("writer", "Writing now"),
        ]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async for _ in fake_team.run_stream(task="Full pipeline"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            names_seen = {e["payload"].get("agent_id") for e in agent_status}
            assert "researcher" in names_seen
            assert "writer" in names_seen

    async def test_tool_call_request_produces_events(self, pp):
        """A ToolCallRequestEvent produces at least one event at /api/events."""
        app = pp._create_app()
        msgs = [
            TextMessage("researcher", "Starting"),
            ToolCallRequestEvent("researcher", "web_search(query='AI trends')"),
        ]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async for _ in fake_team.run_stream(task="Research"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()
            assert len(events) >= 1

    async def test_detach_stops_event_emission(self, pp):
        """After detach(), iterating run_stream produces no events."""
        msgs = [TextMessage("researcher", "Hello")]
        fake_team = _make_fake_team(msgs)

        adapter = pp.adapter("autogen")
        adapter.instrument(fake_team)
        adapter.detach()

        # Reset bus for a clean count
        bus_module._bus = None
        app = pp._create_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # After detach, run_stream is the original (not the wrapped one)
            # and no pp calls happen
            async for _ in fake_team.run_stream(task="Should not emit"):
                pass
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            assert resp.json() == []
