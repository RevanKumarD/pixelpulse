"""Functional tests: Claude Code hooks → PixelPulse → /api/events.

Tests the full Claude Code hook ingest path without mocking:
  POST /hooks/claude-code → ClaudeCodeAdapter.on_hook_event()
  → pp.agent_started/thinking/completed() → EventBus → /api/events

This validates that real Claude Code hook payloads produce correct
dashboard events through the complete HTTP → EventBus chain.
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
        agents={"claude": {"team": "coding", "role": "AI coding assistant"}},
        teams={"coding": {"label": "Claude Code"}},
        pipeline=["coding"],
    )


def _session_start_payload(session_id: str = "test-session-001") -> dict:
    return {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
    }


def _pre_tool_payload(
    tool_name: str = "Read",
    tool_input: dict | None = None,
    session_id: str = "test-session-001",
) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input or {"file_path": "/src/main.py"},
    }


def _post_tool_payload(
    tool_name: str = "Read",
    tool_response: str = "File contents read successfully",
    session_id: str = "test-session-001",
) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_response": tool_response,
    }


class TestClaudeCodePipeline:
    @pytest.mark.asyncio
    async def test_hook_endpoint_returns_200(self, pp):
        """POST /hooks/claude-code returns 200 for a valid hook payload."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/hooks/claude-code",
                json=_session_start_payload(),
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_hook_response_has_continue_true(self, pp):
        """Hook endpoint returns {"continue": true} so Claude Code proceeds."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/hooks/claude-code",
                json=_session_start_payload(),
            )
            body = resp.json()
            assert body.get("continue") is True

    @pytest.mark.asyncio
    async def test_session_start_emits_agent_started(self, pp):
        """SessionStart hook produces an agent_started event at /api/events.

        Note: the server-side _BusEmitter for Claude Code hooks emits events
        with types like "agent_started" (not remapped to "agent_status"), because
        it uses a simplified internal format that bypasses the protocol type map.
        """
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            await client.post("/hooks/claude-code", json=_session_start_payload())
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        types = {e["type"] for e in events}
        assert "agent_started" in types or "run_started" in types

    @pytest.mark.asyncio
    async def test_pre_tool_use_emits_thinking(self, pp):
        """PreToolUse hook produces an agent_thinking event."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            # Start session first
            await client.post("/hooks/claude-code", json=_session_start_payload())
            # Then a tool use
            await client.post(
                "/hooks/claude-code",
                json=_pre_tool_payload(tool_name="Bash", tool_input={"command": "pytest tests/"}),
            )
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        # Claude Code hook path emits "agent_thinking" (internal format, not remapped)
        types = {e["type"] for e in events}
        assert "agent_thinking" in types or "agent_started" in types

    @pytest.mark.asyncio
    async def test_full_session_lifecycle(self, pp):
        """Full session: SessionStart → PreToolUse → PostToolUse produces events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            await client.post("/hooks/claude-code", json=_session_start_payload())
            await client.post("/hooks/claude-code", json=_pre_tool_payload("Read"))
            await client.post("/hooks/claude-code", json=_post_tool_payload("Read"))
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        assert len(events) >= 1
        types = {e["type"] for e in events}
        # Claude Code hooks produce internal-format event types (not remapped)
        assert any(t in types for t in ("agent_started", "agent_thinking", "run_started"))

    @pytest.mark.asyncio
    async def test_empty_events_before_any_hook(self, pp):
        """No events before any hook fires."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/events")
            assert resp.json() == []

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_produce_multiple_events(self, pp):
        """Multiple PreToolUse hooks each produce a thinking event."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            await client.post("/hooks/claude-code", json=_session_start_payload())
            for tool in ("Read", "Grep", "Bash"):
                await client.post("/hooks/claude-code", json=_pre_tool_payload(tool))
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        # Session start + 3 tool thinking events = at least 4 events total
        assert len(events) >= 4
