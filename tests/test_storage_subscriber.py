"""Integration tests for StorageSubscriber — events flow from bus to SQLite."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from pixelpulse.bus import EventBus
from pixelpulse.storage.db import Database
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.models import RunStatus
from pixelpulse.storage.run_repo import RunRepository
from pixelpulse.storage.subscriber import StorageSubscriber


@pytest_asyncio.fixture
async def db(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def bus():
    return EventBus()


@pytest_asyncio.fixture
async def subscriber(db, bus):
    sub = StorageSubscriber(db)
    await sub.attach(bus)
    yield sub
    await sub.detach(bus)


@pytest.fixture
def runs(db):
    return RunRepository(db)


@pytest.fixture
def events(db):
    return EventRepository(db)


class TestRunLifecycle:
    async def test_run_started_creates_record(self, bus, subscriber, runs):
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: My Run"},
        })
        assert subscriber.current_run_id is not None
        run = await runs.get(subscriber.current_run_id)
        assert run is not None
        assert run.name == "My Run"
        assert run.status == RunStatus.ACTIVE

    async def test_run_completed_updates_status(self, bus, subscriber, runs):
        # Start a run
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Test"},
        })
        run_id = subscriber.current_run_id

        # Emit a cost event
        await bus.emit({
            "type": "cost_update",
            "timestamp": "2026-03-27T10:00:01Z",
            "payload": {"agent_id": "researcher", "cost": 0.05, "tokens_in": 500, "tokens_out": 200},
        })

        # Complete the run
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:05:00Z",
            "payload": {"stage": "completed", "status": "completed", "message": "Run completed"},
        })

        run = await runs.get(run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at == "2026-03-27T10:05:00Z"
        assert run.total_cost == pytest.approx(0.05)
        assert run.total_tokens_in == 500
        assert subscriber.current_run_id is None

    async def test_run_failed_status(self, bus, subscriber, runs):
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Fail Test"},
        })
        run_id = subscriber.current_run_id

        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:01:00Z",
            "payload": {"stage": "completed", "status": "failed"},
        })

        run = await runs.get(run_id)
        assert run.status == RunStatus.FAILED


class TestEventPersistence:
    async def test_events_saved(self, bus, subscriber, events):
        # Emit a run start first
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Test"},
        })
        run_id = subscriber.current_run_id

        # Emit agent events
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:01Z",
            "payload": {"agent_id": "researcher", "status": "active", "thinking": "Working..."},
        })
        await bus.emit({
            "type": "message_flow",
            "timestamp": "2026-03-27T10:00:02Z",
            "payload": {"from": "researcher", "to": "writer", "content": "Data ready"},
        })

        saved = await events.list_by_run(run_id)
        assert len(saved) == 2
        assert saved[0].type == "agent_status"
        assert saved[0].agent_id == "researcher"
        assert saved[1].type == "message_flow"
        assert saved[1].agent_id == "researcher"  # extracted from 'from' field

    async def test_cost_accumulation(self, bus, subscriber, events, runs):
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Cost Test"},
        })
        run_id = subscriber.current_run_id

        for i in range(3):
            await bus.emit({
                "type": "cost_update",
                "timestamp": f"2026-03-27T10:00:0{i + 1}Z",
                "payload": {"agent_id": "researcher", "cost": 0.01, "tokens_in": 100, "tokens_out": 50},
            })

        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:05:00Z",
            "payload": {"stage": "completed", "status": "completed"},
        })

        run = await runs.get(run_id)
        assert run.total_cost == pytest.approx(0.03)
        assert run.total_tokens_in == 300
        assert run.total_tokens_out == 150


class TestDefaultRun:
    async def test_auto_creates_default_run(self, bus, subscriber, runs):
        # Emit event without run.started
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"agent_id": "researcher", "status": "active"},
        })

        assert subscriber.current_run_id is not None
        run = await runs.get(subscriber.current_run_id)
        assert run.name == "Default Session"


class TestAgentTracking:
    async def test_agents_counted(self, bus, subscriber, runs):
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Agent Count"},
        })
        run_id = subscriber.current_run_id

        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:01Z",
            "payload": {"agent_id": "researcher", "status": "active"},
        })
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:02Z",
            "payload": {"agent_id": "writer", "status": "active"},
        })
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:03Z",
            "payload": {"agent_id": "researcher", "status": "idle"},
        })

        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:05:00Z",
            "payload": {"stage": "completed", "status": "completed"},
        })

        run = await runs.get(run_id)
        assert run.agent_count == 2  # researcher + writer (deduped)
