"""Unit tests for EventRepository."""
from __future__ import annotations

import pytest
import pytest_asyncio

from pixelpulse.storage.db import Database
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
from pixelpulse.storage.run_repo import RunRepository


@pytest_asyncio.fixture
async def db(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    # Create a run to attach events to
    run_repo = RunRepository(db)
    await run_repo.create(RunRecord(
        id="run_test", name="Test", status=RunStatus.ACTIVE,
        started_at="2026-03-27T10:00:00Z",
    ))
    yield db
    await db.close()


@pytest.fixture
def repo(db):
    return EventRepository(db)


def _make_event(event_id: str = "evt_1", **kw) -> EventRecord:
    defaults = {
        "run_id": "run_test",
        "type": "agent_status",
        "timestamp": "2026-03-27T10:00:01Z",
        "payload": {"status": "active", "agent_id": "researcher"},
        "agent_id": "researcher",
    }
    defaults.update(kw)
    return EventRecord(id=event_id, **defaults)


class TestEventCreate:
    async def test_create_and_get(self, repo):
        event = _make_event()
        created = await repo.create(event)
        assert created.id == "evt_1"

        fetched = await repo.get("evt_1")
        assert fetched is not None
        assert fetched.type == "agent_status"
        assert fetched.payload == {"status": "active", "agent_id": "researcher"}

    async def test_get_nonexistent(self, repo):
        assert await repo.get("nope") is None


class TestEventListByRun:
    async def test_list_empty_run(self, repo):
        events = await repo.list_by_run("run_test")
        assert events == []

    async def test_list_events(self, repo):
        for i in range(5):
            await repo.create(_make_event(
                event_id=f"evt_{i}",
                timestamp=f"2026-03-27T10:00:0{i}Z",
            ))
        events = await repo.list_by_run("run_test")
        assert len(events) == 5
        # Ordered by timestamp ASC
        assert events[0].id == "evt_0"
        assert events[4].id == "evt_4"

    async def test_filter_by_type(self, repo):
        await repo.create(_make_event(event_id="evt_1", type="agent_status"))
        await repo.create(_make_event(event_id="evt_2", type="cost_update"))
        await repo.create(_make_event(event_id="evt_3", type="agent_status"))

        status_events = await repo.list_by_run("run_test", event_type="agent_status")
        assert len(status_events) == 2
        cost_events = await repo.list_by_run("run_test", event_type="cost_update")
        assert len(cost_events) == 1

    async def test_filter_by_agent(self, repo):
        await repo.create(_make_event(event_id="evt_1", agent_id="researcher"))
        await repo.create(_make_event(event_id="evt_2", agent_id="writer"))
        await repo.create(_make_event(event_id="evt_3", agent_id="researcher"))

        events = await repo.list_by_run("run_test", agent_id="researcher")
        assert len(events) == 2

    async def test_limit_and_offset(self, repo):
        for i in range(10):
            await repo.create(_make_event(
                event_id=f"evt_{i}",
                timestamp=f"2026-03-27T10:00:{i:02d}Z",
            ))
        events = await repo.list_by_run("run_test", limit=3, offset=2)
        assert len(events) == 3
        assert events[0].id == "evt_2"


class TestEventListByAgent:
    async def test_list_by_agent(self, repo):
        await repo.create(_make_event(event_id="evt_1", agent_id="researcher"))
        await repo.create(_make_event(event_id="evt_2", agent_id="writer"))
        await repo.create(_make_event(event_id="evt_3", agent_id="researcher"))

        events = await repo.list_by_agent("researcher")
        assert len(events) == 2

    async def test_list_by_agent_with_run(self, repo, db):
        # Create a second run
        run_repo = RunRepository(db)
        await run_repo.create(RunRecord(
            id="run_2", name="Run 2", status=RunStatus.ACTIVE,
            started_at="2026-03-27T11:00:00Z",
        ))
        await repo.create(_make_event(event_id="evt_1", agent_id="researcher", run_id="run_test"))
        await repo.create(_make_event(event_id="evt_2", agent_id="researcher", run_id="run_2"))

        all_events = await repo.list_by_agent("researcher")
        assert len(all_events) == 2

        run1_events = await repo.list_by_agent("researcher", run_id="run_test")
        assert len(run1_events) == 1


class TestEventCount:
    async def test_count_empty(self, repo):
        assert await repo.count_by_run("run_test") == 0

    async def test_count(self, repo):
        for i in range(7):
            await repo.create(_make_event(event_id=f"evt_{i}"))
        assert await repo.count_by_run("run_test") == 7


class TestEventAgentIds:
    async def test_get_agent_ids(self, repo):
        await repo.create(_make_event(event_id="evt_1", agent_id="researcher"))
        await repo.create(_make_event(event_id="evt_2", agent_id="writer"))
        await repo.create(_make_event(event_id="evt_3", agent_id="researcher"))
        await repo.create(_make_event(event_id="evt_4", agent_id=""))

        ids = await repo.get_agent_ids_for_run("run_test")
        assert set(ids) == {"researcher", "writer"}


class TestEventCostSummary:
    async def test_cost_summary(self, repo):
        await repo.create(_make_event(
            event_id="evt_1", type="cost_update",
            payload={"cost": 0.01, "tokens_in": 100, "tokens_out": 50, "agent_id": "researcher", "model": "claude-3"},
        ))
        await repo.create(_make_event(
            event_id="evt_2", type="cost_update",
            payload={"cost": 0.02, "tokens_in": 200, "tokens_out": 100, "agent_id": "writer", "model": "gpt-4"},
        ))
        await repo.create(_make_event(
            event_id="evt_3", type="cost_update",
            payload={"cost": 0.005, "tokens_in": 50, "tokens_out": 25, "agent_id": "researcher", "model": "claude-3"},
        ))

        summary = await repo.get_cost_summary("run_test")
        assert summary["total_cost"] == pytest.approx(0.035)
        assert summary["total_tokens_in"] == 350
        assert summary["total_tokens_out"] == 175
        assert len(summary["by_agent"]) == 2
        assert summary["by_agent"]["researcher"]["cost"] == pytest.approx(0.015)
        assert summary["by_agent"]["writer"]["model"] == "gpt-4"

    async def test_cost_summary_empty(self, repo):
        summary = await repo.get_cost_summary("run_test")
        assert summary["total_cost"] == 0
        assert summary["by_agent"] == {}


class TestEventDelete:
    async def test_delete_by_run(self, repo):
        for i in range(5):
            await repo.create(_make_event(event_id=f"evt_{i}"))
        deleted = await repo.delete_by_run("run_test")
        assert deleted == 5
        assert await repo.count_by_run("run_test") == 0

    async def test_delete_nonexistent_run(self, repo):
        assert await repo.delete_by_run("nope") == 0
