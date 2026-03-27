"""Integration tests for Run History API endpoints."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from pixelpulse.config import AgentConfig, TeamConfig
from pixelpulse.server import create_app
from pixelpulse.storage.db import Database
from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.run_repo import RunRepository


@pytest_asyncio.fixture
async def db(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def agents():
    return {"researcher": AgentConfig(role="Research", team="research")}


@pytest.fixture
def teams():
    return {"research": TeamConfig(label="Research", color="#00d4ff")}


@pytest_asyncio.fixture
async def seeded_db(db):
    """Seed the database with test data."""
    run_repo = RunRepository(db)
    event_repo = EventRepository(db)

    # Create 3 runs
    for i in range(3):
        status = RunStatus.COMPLETED if i < 2 else RunStatus.ACTIVE
        await run_repo.create(RunRecord(
            id=f"run_{i}",
            name=f"Test Run {i}",
            status=status,
            started_at=f"2026-03-27T1{i}:00:00Z",
            completed_at=f"2026-03-27T1{i}:05:00Z" if i < 2 else "",
            total_cost=0.01 * (i + 1),
            event_count=5 * (i + 1),
            agent_count=2,
        ))

    # Add events to run_0
    for j in range(5):
        await event_repo.create(EventRecord(
            id=f"evt_{j}",
            run_id="run_0",
            type="agent_status",
            timestamp=f"2026-03-27T10:00:0{j}Z",
            payload={"agent_id": "researcher", "status": "active" if j % 2 == 0 else "idle"},
            agent_id="researcher",
        ))

    # Add a cost event
    await event_repo.create(EventRecord(
        id="evt_cost_1",
        run_id="run_0",
        type="cost_update",
        timestamp="2026-03-27T10:00:06Z",
        payload={"agent_id": "researcher", "cost": 0.01, "tokens_in": 100, "tokens_out": 50, "model": "claude-3"},
        agent_id="researcher",
    ))

    return db


@pytest_asyncio.fixture
async def client(agents, teams, seeded_db, tmp_path):
    """Create a test client with storage enabled."""
    app = create_app(agents, teams, db_path=tmp_path / "test.db")

    # Manually set up storage state (since lifespan doesn't run in test)
    # We use the seeded_db directly
    from pixelpulse.storage.event_repo import EventRepository
    from pixelpulse.storage.run_repo import RunRepository

    app.state.storage = {
        "db": seeded_db,
        "runs": RunRepository(seeded_db),
        "events": EventRepository(seeded_db),
    }
    # Patch the _storage dict in the closure
    # We need to access the internal _storage dict
    # Since create_app uses closure state, we'll test through the endpoints directly

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestListRuns:
    async def test_list_runs_no_storage(self, agents, teams):
        app = create_app(agents, teams, db_path=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/runs")
            assert resp.status_code == 200
            data = resp.json()
            assert data["storage_enabled"] is False
            assert data["runs"] == []


class TestRunEndpointsNoStorage:
    """Test that endpoints gracefully handle no storage."""

    async def test_get_run_no_storage(self, agents, teams):
        app = create_app(agents, teams, db_path=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/runs/run_0")
            assert resp.status_code == 503

    async def test_get_run_events_no_storage(self, agents, teams):
        app = create_app(agents, teams, db_path=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/runs/run_0/events")
            assert resp.status_code == 503

    async def test_delete_run_no_storage(self, agents, teams):
        app = create_app(agents, teams, db_path=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/runs/run_0")
            assert resp.status_code == 503

    async def test_agent_events_no_storage(self, agents, teams):
        app = create_app(agents, teams, db_path=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/agents/researcher/events")
            assert resp.status_code == 503

    async def test_agent_stats_no_storage(self, agents, teams):
        app = create_app(agents, teams, db_path=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/agents/researcher/stats")
            assert resp.status_code == 503


class TestHealthAndConfig:
    """Verify existing endpoints still work."""

    async def test_health(self, agents, teams):
        app = create_app(agents, teams)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    async def test_config(self, agents, teams):
        app = create_app(agents, teams)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert "researcher" in data["agents"]
            assert "research" in data["teams"]
