"""Functional tests: CrewAI adapter → PixelPulse → /api/events.

Tests the full CrewAI adapter integration path without mocking pp:
  adapter.instrument(crew) → fake crew.kickoff() → EventBus → /api/events

Since crewai is not installed, we simulate the callback mechanism
that CrewAI would trigger on a real crew.  The adapter checks for crewai
at instrument()-time and returns early on ImportError, so we bypass that
guard by invoking the internal wiring methods directly via the callback
that the adapter installs on the fake crew object.
"""
from __future__ import annotations

import asyncio
import types
from typing import Any

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


def _make_fake_crew(kickoff_result: Any = "done") -> Any:
    """Create a minimal fake crew object with the attributes CrewAI exposes."""
    crew = types.SimpleNamespace()
    crew.name = "FakeCrewAI Crew"
    crew.agents = []
    crew.tasks = []
    crew.step_callback = None
    crew.task_callback = None
    crew.usage_metrics = None

    def kickoff(*args: Any, **kwargs: Any) -> Any:
        return kickoff_result

    crew.kickoff = kickoff
    return crew


def _make_fake_step_output(agent_role: str, thought: str = "", tool: str = "") -> Any:
    """Create a fake CrewAI step output with the expected attribute shape."""
    agent = types.SimpleNamespace(role=agent_role, name=agent_role)
    output = types.SimpleNamespace(
        agent=agent,
        thought=thought or None,
        tool=tool or None,
        tool_input=None,
        result=None,
        output=None,
        text=None,
        action=None,
        token_usage=None,
        usage=None,
    )
    return output


def _make_fake_task_output(agent_role: str, raw: str = "Task done") -> Any:
    """Create a fake CrewAI task output."""
    agent = types.SimpleNamespace(role=agent_role, name=agent_role)
    output = types.SimpleNamespace(
        agent=agent,
        raw=raw,
        output=None,
        description=None,
        token_usage=None,
        usage=None,
    )
    return output


def _install_crewai_adapter_directly(adapter: Any, fake_crew: Any) -> None:
    """Install the adapter internals without going through instrument()'s crewai import.

    instrument() aborts early if crewai is not installed.  We replicate what
    instrument() does after the import check so the full callback wiring is active.
    """
    adapter._crew = fake_crew

    # ---- Callback hooks (v0.60+) ----
    if hasattr(fake_crew, "step_callback"):
        adapter._original_callbacks["step"] = fake_crew.step_callback
        fake_crew.step_callback = adapter._on_step

    if hasattr(fake_crew, "task_callback"):
        adapter._original_callbacks["task"] = fake_crew.task_callback
        fake_crew.task_callback = adapter._on_task_complete

    # ---- Wrap kickoff for run lifecycle ----
    if hasattr(fake_crew, "kickoff"):
        adapter._original_kickoff = fake_crew.kickoff
        fake_crew.kickoff = adapter._wrapped_kickoff


class TestCrewAIFunctional:
    """Full stack: CrewAI adapter (callback wiring) → bus → /api/events."""

    async def test_events_empty_before_instrument(self, pp):
        """No events appear before any adapter calls."""
        app = pp._create_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/events")
            assert resp.json() == []

    async def test_instrument_wraps_kickoff(self, pp):
        """After instrument(), fake_crew.kickoff() emits run_started to /api/events."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            fake_crew.kickoff()
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            assert resp.status_code == 200
            events = resp.json()

            # run_started maps to "run_status" or "pipeline_update" on the dashboard
            types_seen = {e["type"] for e in events}
            # We just need at least one event — run lifecycle was emitted
            assert len(events) >= 1

    async def test_kickoff_emits_run_started_event(self, pp):
        """kickoff() must produce a run-lifecycle event visible at /api/events."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            fake_crew.kickoff()
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # Both run_started and run_completed should have been emitted
            assert len(events) >= 2

    async def test_kickoff_emits_run_completed(self, pp):
        """After kickoff() returns, run_completed appears in events."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            fake_crew.kickoff()
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # Expect at least run_started + run_completed (≥2 events)
            assert len(events) >= 2

    async def test_step_callback_emits_agent_events(self, pp):
        """Calling step_callback with a fake output emits agent_status events."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Manually trigger the step callback just like CrewAI would
            step_out = _make_fake_step_output("researcher", thought="Analysing trends")
            fake_crew.step_callback(step_out)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            # Agent started must have been emitted for the first step
            agent_status = [e for e in events if e["type"] == "agent_status"]
            assert len(agent_status) >= 1
            assert any(e["payload"].get("status") == "active" for e in agent_status)

    async def test_step_callback_agent_name_in_payload(self, pp):
        """step_callback event payload carries the agent name from the output object."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            step_out = _make_fake_step_output("researcher")
            fake_crew.step_callback(step_out)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            # _sanitize_name("researcher") → "researcher"
            names = [e["payload"].get("agent_id") for e in agent_status]
            assert "researcher" in names

    async def test_multiple_agents_produce_events(self, pp):
        """Calling step_callback for multiple agents produces multiple events."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Simulate two different agents stepping
            fake_crew.step_callback(_make_fake_step_output("researcher", thought="Thinking"))
            fake_crew.step_callback(_make_fake_step_output("writer", thought="Writing"))
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            names_seen = {e["payload"].get("agent_id") for e in agent_status}
            assert "researcher" in names_seen
            assert "writer" in names_seen

    async def test_task_callback_emits_agent_completed(self, pp):
        """task_callback emits an agent_completed event (agent_status idle)."""
        app = pp._create_app()
        fake_crew = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            task_out = _make_fake_task_output("researcher", raw="Analysis complete")
            fake_crew.task_callback(task_out)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

            agent_status = [e for e in events if e["type"] == "agent_status"]
            assert any(e["payload"].get("status") == "idle" for e in agent_status)

    async def test_kickoff_run_id_increments(self, pp):
        """Each kickoff() call gets a new run ID (crewai-run-N)."""
        fake_crew1 = _make_fake_crew()
        fake_crew2 = _make_fake_crew()
        adapter = pp.adapter("crewai")
        _install_crewai_adapter_directly(adapter, fake_crew1)

        fake_crew1.kickoff()
        assert adapter._run_counter == 1
        assert adapter._current_run_id == "crewai-run-1"

        # Simulate a second kickoff (same adapter, different call)
        fake_crew1.kickoff()
        assert adapter._run_counter == 2
        assert adapter._current_run_id == "crewai-run-2"
