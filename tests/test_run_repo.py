"""Unit tests for RunRepository."""
from __future__ import annotations

import pytest
import pytest_asyncio

from pixelpulse.storage.db import Database
from pixelpulse.storage.models import RunRecord, RunStatus
from pixelpulse.storage.run_repo import RunRepository


@pytest_asyncio.fixture
async def db(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def repo(db):
    return RunRepository(db)


def _make_run(run_id: str = "run_test", **kw) -> RunRecord:
    defaults = {
        "name": "Test Run",
        "status": RunStatus.ACTIVE,
        "started_at": "2026-03-27T10:00:00Z",
    }
    defaults.update(kw)
    return RunRecord(id=run_id, **defaults)


class TestRunCreate:
    async def test_create_and_get(self, repo):
        run = _make_run()
        created = await repo.create(run)
        assert created.id == "run_test"

        fetched = await repo.get("run_test")
        assert fetched is not None
        assert fetched.name == "Test Run"
        assert fetched.status == RunStatus.ACTIVE

    async def test_create_with_metadata(self, repo):
        run = _make_run(metadata={"key": "value"})
        await repo.create(run)
        fetched = await repo.get("run_test")
        assert fetched.metadata == {"key": "value"}


class TestRunList:
    async def test_list_empty(self, repo):
        runs = await repo.list_all()
        assert runs == []

    async def test_list_multiple(self, repo):
        for i in range(5):
            await repo.create(_make_run(
                run_id=f"run_{i}",
                started_at=f"2026-03-27T10:0{i}:00Z",
            ))
        runs = await repo.list_all()
        assert len(runs) == 5
        # Newest first
        assert runs[0].id == "run_4"

    async def test_list_with_limit(self, repo):
        for i in range(10):
            await repo.create(_make_run(
                run_id=f"run_{i}",
                started_at=f"2026-03-27T10:{i:02d}:00Z",
            ))
        runs = await repo.list_all(limit=3)
        assert len(runs) == 3

    async def test_list_with_offset(self, repo):
        for i in range(5):
            await repo.create(_make_run(
                run_id=f"run_{i}",
                started_at=f"2026-03-27T10:0{i}:00Z",
            ))
        runs = await repo.list_all(offset=2)
        assert len(runs) == 3

    async def test_list_by_status(self, repo):
        await repo.create(_make_run(run_id="run_a", status=RunStatus.ACTIVE))
        await repo.create(_make_run(run_id="run_b", status=RunStatus.COMPLETED))
        await repo.create(_make_run(run_id="run_c", status=RunStatus.ACTIVE))

        active = await repo.list_all(status=RunStatus.ACTIVE)
        assert len(active) == 2
        completed = await repo.list_all(status=RunStatus.COMPLETED)
        assert len(completed) == 1


class TestRunCount:
    async def test_count_empty(self, repo):
        assert await repo.count() == 0

    async def test_count_all(self, repo):
        for i in range(3):
            await repo.create(_make_run(run_id=f"run_{i}"))
        assert await repo.count() == 3

    async def test_count_by_status(self, repo):
        await repo.create(_make_run(run_id="run_a", status=RunStatus.ACTIVE))
        await repo.create(_make_run(run_id="run_b", status=RunStatus.COMPLETED))
        assert await repo.count(status=RunStatus.ACTIVE) == 1
        assert await repo.count(status=RunStatus.COMPLETED) == 1


class TestRunUpdate:
    async def test_update_status(self, repo):
        await repo.create(_make_run())
        updated = await repo.update_status(
            "run_test",
            status=RunStatus.COMPLETED,
            completed_at="2026-03-27T10:05:00Z",
            total_cost=0.42,
            total_tokens_in=2000,
            total_tokens_out=1000,
        )
        assert updated.status == RunStatus.COMPLETED
        assert updated.completed_at == "2026-03-27T10:05:00Z"
        assert updated.total_cost == 0.42
        assert updated.total_tokens_in == 2000

    async def test_increment_event_count(self, repo):
        await repo.create(_make_run())
        await repo.increment_event_count("run_test")
        await repo.increment_event_count("run_test")
        await repo.increment_event_count("run_test")
        run = await repo.get("run_test")
        assert run.event_count == 3

    async def test_update_agent_count(self, repo):
        await repo.create(_make_run())
        await repo.update_agent_count("run_test", 5)
        run = await repo.get("run_test")
        assert run.agent_count == 5


class TestRunDelete:
    async def test_delete_existing(self, repo):
        await repo.create(_make_run())
        assert await repo.delete("run_test") is True
        assert await repo.get("run_test") is None

    async def test_delete_nonexistent(self, repo):
        assert await repo.delete("nope") is False

    async def test_get_nonexistent(self, repo):
        assert await repo.get("nope") is None


class TestRunExport:
    async def test_export_run(self, repo, db):
        from pixelpulse.storage.event_repo import EventRepository
        from pixelpulse.storage.models import EventRecord

        await repo.create(_make_run())
        event_repo = EventRepository(db)
        await event_repo.create(EventRecord(
            id="evt_1", run_id="run_test", type="agent_status",
            timestamp="2026-03-27T10:00:01Z", payload={"status": "active"},
        ))
        await event_repo.create(EventRecord(
            id="evt_2", run_id="run_test", type="cost_update",
            timestamp="2026-03-27T10:00:02Z", payload={"cost": 0.01},
        ))

        export = await repo.export_run("run_test")
        assert export["version"] == 1
        assert export["run"]["id"] == "run_test"
        assert len(export["events"]) == 2
        assert export["events"][0]["id"] == "evt_1"

    async def test_export_nonexistent(self, repo):
        assert await repo.export_run("nope") is None
