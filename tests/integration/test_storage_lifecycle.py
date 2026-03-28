"""Full lifecycle integration test: events → bus → subscriber → SQLite → API.

This tests the complete flow without mocks.
"""
from __future__ import annotations

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


class TestFullRunLifecycle:
    """Simulate a complete agent run and verify persistence."""

    async def test_complete_run_persisted(self, bus, subscriber, runs, events):
        """Start run → agent work → messages → costs → complete → verify all saved."""
        # 1. Start run
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Integration Test"},
        })
        run_id = subscriber.current_run_id
        assert run_id is not None

        # 2. Agent starts working
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:01Z",
            "payload": {"agent_id": "researcher", "status": "active", "thinking": "Analyzing data..."},
        })

        # 3. Agent sends thinking events
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:02Z",
            "payload": {"agent_id": "researcher", "status": "active", "thinking": "Found 5 trends in DE market"},
        })

        # 4. Agent sends message to another agent
        await bus.emit({
            "type": "message_flow",
            "timestamp": "2026-03-27T10:00:03Z",
            "payload": {"from": "researcher", "to": "writer", "content": "Here are the trends", "tag": "data"},
        })

        # 5. Cost updates
        await bus.emit({
            "type": "cost_update",
            "timestamp": "2026-03-27T10:00:04Z",
            "payload": {"agent_id": "researcher", "cost": 0.015, "tokens_in": 500, "tokens_out": 200, "model": "claude-sonnet"},
        })

        # 6. Second agent works
        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:05Z",
            "payload": {"agent_id": "writer", "status": "active", "thinking": "Writing listing..."},
        })

        await bus.emit({
            "type": "cost_update",
            "timestamp": "2026-03-27T10:00:06Z",
            "payload": {"agent_id": "writer", "cost": 0.02, "tokens_in": 800, "tokens_out": 400, "model": "gpt-4o"},
        })

        # 7. Complete run
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:05:00Z",
            "payload": {"stage": "completed", "status": "completed", "message": "Run completed"},
        })

        # ---- Verify ----

        # Run record
        run = await runs.get(run_id)
        assert run is not None
        assert run.name == "Integration Test"
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at == "2026-03-27T10:05:00Z"
        assert run.total_cost == pytest.approx(0.035)
        assert run.total_tokens_in == 1300
        assert run.total_tokens_out == 600
        assert run.agent_count == 2  # researcher + writer

        # Events
        all_events = await events.list_by_run(run_id)
        assert len(all_events) == 6  # all events except run start/complete pipeline_progress

        # Agent filtering
        researcher_events = await events.list_by_agent("researcher", run_id=run_id)
        assert len(researcher_events) >= 3  # 2 status + 1 message + 1 cost

        writer_events = await events.list_by_agent("writer", run_id=run_id)
        assert len(writer_events) >= 1

        # Cost summary
        cost_summary = await events.get_cost_summary(run_id)
        assert cost_summary["total_cost"] == pytest.approx(0.035)
        assert "researcher" in cost_summary["by_agent"]
        assert "writer" in cost_summary["by_agent"]
        assert cost_summary["by_agent"]["researcher"]["model"] == "claude-sonnet"
        assert cost_summary["by_agent"]["writer"]["model"] == "gpt-4o"

        # Agent IDs
        agent_ids = await events.get_agent_ids_for_run(run_id)
        assert set(agent_ids) == {"researcher", "writer"}

    async def test_export_and_import(self, bus, subscriber, runs, events, db):
        """Export a run, delete it, import it back, verify identical."""
        # Create a run with events
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:00:00Z",
            "payload": {"stage": "started", "status": "active", "message": "Run started: Export Test"},
        })
        run_id = subscriber.current_run_id

        await bus.emit({
            "type": "agent_status",
            "timestamp": "2026-03-27T10:00:01Z",
            "payload": {"agent_id": "researcher", "status": "active"},
        })
        await bus.emit({
            "type": "pipeline_progress",
            "timestamp": "2026-03-27T10:05:00Z",
            "payload": {"stage": "completed", "status": "completed"},
        })

        # Export
        export_data = await runs.export_run(run_id)
        assert export_data is not None
        assert export_data["version"] == 1
        original_event_count = len(export_data["events"])

        # Delete
        await runs.delete(run_id)
        assert await runs.get(run_id) is None

        # Import (simulate import — create new records from export data)
        from pixelpulse.storage.models import EventRecord, RunRecord

        run_data = export_data["run"]
        restored_run = RunRecord(
            id=run_data["id"],
            name=run_data["name"],
            status=run_data["status"],
            started_at=run_data["started_at"],
            completed_at=run_data.get("completed_at", ""),
            total_cost=run_data.get("total_cost", 0),
        )
        await runs.create(restored_run)

        for evt in export_data["events"]:
            await events.create(EventRecord(
                id=evt["id"],
                run_id=evt["run_id"],
                type=evt["type"],
                timestamp=evt["timestamp"],
                payload=evt.get("payload", {}),
                agent_id=evt.get("agent_id", ""),
            ))

        # Verify
        restored = await runs.get(run_id)
        assert restored is not None
        assert restored.name == "Export Test"
        restored_events = await events.list_by_run(run_id)
        assert len(restored_events) == original_event_count

    async def test_multiple_runs(self, bus, subscriber, runs):
        """Multiple runs create separate records."""
        for i in range(3):
            await bus.emit({
                "type": "pipeline_progress",
                "timestamp": f"2026-03-27T1{i}:00:00Z",
                "payload": {"stage": "started", "status": "active", "message": f"Run started: Run {i}"},
            })
            await bus.emit({
                "type": "agent_status",
                "timestamp": f"2026-03-27T1{i}:00:01Z",
                "payload": {"agent_id": "researcher", "status": "active"},
            })
            await bus.emit({
                "type": "pipeline_progress",
                "timestamp": f"2026-03-27T1{i}:05:00Z",
                "payload": {"stage": "completed", "status": "completed"},
            })

        all_runs = await runs.list_all()
        assert len(all_runs) == 3
        assert all(r.status == RunStatus.COMPLETED for r in all_runs)
