"""Integration tests for all Run History + Agent Detail API endpoints with real storage.

These tests verify the complete API ↔ Storage flow by using LifespanManager
to properly initialize SQLite storage via the app lifespan, then querying
seeded data through the REST endpoints.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from pixelpulse.bus import EventBus
from pixelpulse.config import AgentConfig, TeamConfig
from pixelpulse.server import create_app
from pixelpulse.storage.db import Database
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
from pixelpulse.storage.run_repo import RunRepository


# ---- Fixtures ----

@pytest.fixture
def agents():
    return {
        "researcher": AgentConfig(role="Research", team="research"),
        "writer": AgentConfig(role="Writing", team="design"),
    }


@pytest.fixture
def teams():
    return {
        "research": TeamConfig(label="Research", color="#00d4ff"),
        "design": TeamConfig(label="Design", color="#ff6ec7"),
    }


@pytest_asyncio.fixture
async def seeded_db(tmp_path):
    """Create a DB and seed it with test data directly."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.connect()

    run_repo = RunRepository(db)
    event_repo = EventRepository(db)

    # Create 2 completed runs + 1 active
    for i in range(3):
        status = "completed" if i < 2 else "active"
        await run_repo.create(RunRecord(
            id=f"run_{i}",
            name=f"Test Run {i}",
            status=status,
            started_at=f"2026-03-27T1{i}:00:00Z",
            completed_at=f"2026-03-27T1{i}:05:00Z" if i < 2 else "",
            total_cost=0.01 * (i + 1),
            total_tokens_in=100 * (i + 1),
            total_tokens_out=50 * (i + 1),
            event_count=5 * (i + 1),
            agent_count=2,
        ))

    # Seed events for run_0
    await event_repo.create(EventRecord(
        id="evt_status_1", run_id="run_0", type="agent_status",
        timestamp="2026-03-27T10:00:01Z",
        payload={"agent_id": "researcher", "status": "active", "thinking": "Analyzing data"},
        agent_id="researcher",
    ))
    await event_repo.create(EventRecord(
        id="evt_status_2", run_id="run_0", type="agent_status",
        timestamp="2026-03-27T10:00:02Z",
        payload={"agent_id": "researcher", "status": "idle"},
        agent_id="researcher",
    ))
    await event_repo.create(EventRecord(
        id="evt_msg_1", run_id="run_0", type="message_flow",
        timestamp="2026-03-27T10:00:03Z",
        payload={"from": "researcher", "to": "writer", "content": "Here are the trends", "tag": "data"},
        agent_id="researcher",
    ))
    await event_repo.create(EventRecord(
        id="evt_cost_1", run_id="run_0", type="cost_update",
        timestamp="2026-03-27T10:00:04Z",
        payload={"agent_id": "researcher", "cost": 0.015, "tokens_in": 500, "tokens_out": 200, "model": "claude-sonnet"},
        agent_id="researcher",
    ))
    await event_repo.create(EventRecord(
        id="evt_cost_2", run_id="run_0", type="cost_update",
        timestamp="2026-03-27T10:00:05Z",
        payload={"agent_id": "writer", "cost": 0.02, "tokens_in": 800, "tokens_out": 400, "model": "gpt-4o"},
        agent_id="writer",
    ))
    await event_repo.create(EventRecord(
        id="evt_pipeline_1", run_id="run_0", type="pipeline_progress",
        timestamp="2026-03-27T10:00:06Z",
        payload={"stage": "design", "status": "active", "message": "Design phase started"},
        agent_id="",
    ))
    # Error event
    await event_repo.create(EventRecord(
        id="evt_err_1", run_id="run_0", type="error",
        timestamp="2026-03-27T10:00:07Z",
        payload={"agent_id": "writer", "error": "Rate limit hit"},
        agent_id="writer",
    ))

    await db.close()
    return db_path


@pytest_asyncio.fixture
async def client(agents, teams, seeded_db):
    """Create app with lifespan-managed storage pointing at seeded DB."""
    app = create_app(agents, teams, db_path=seeded_db)
    async with LifespanManager(app) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app),
            base_url="http://test",
        ) as ac:
            yield ac


# ---- Run List Tests ----

class TestListRuns:
    async def test_lists_all_runs(self, client):
        resp = await client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["storage_enabled"] is True
        assert data["total"] == 3
        assert len(data["runs"]) == 3

    async def test_pagination_limit(self, client):
        resp = await client.get("/api/runs?limit=2")
        data = resp.json()
        assert len(data["runs"]) == 2
        assert data["total"] == 3

    async def test_pagination_offset(self, client):
        resp = await client.get("/api/runs?limit=2&offset=2")
        data = resp.json()
        assert len(data["runs"]) == 1

    async def test_filter_by_status(self, client):
        resp = await client.get("/api/runs?status=completed")
        data = resp.json()
        assert data["total"] == 2
        assert all(r["status"] == "completed" for r in data["runs"])

    async def test_filter_active(self, client):
        resp = await client.get("/api/runs?status=active")
        data = resp.json()
        assert data["total"] == 1
        assert data["runs"][0]["name"] == "Test Run 2"

    async def test_run_has_expected_fields(self, client):
        resp = await client.get("/api/runs")
        run = resp.json()["runs"][0]
        assert "id" in run
        assert "name" in run
        assert "status" in run
        assert "started_at" in run
        assert "total_cost" in run


# ---- Get Run Detail ----

class TestGetRun:
    async def test_get_existing_run(self, client):
        resp = await client.get("/api/runs/run_0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run"]["id"] == "run_0"
        assert data["run"]["name"] == "Test Run 0"
        assert "cost_summary" in data
        assert "agent_ids" in data

    async def test_get_run_cost_summary(self, client):
        resp = await client.get("/api/runs/run_0")
        data = resp.json()
        summary = data["cost_summary"]
        assert summary["total_cost"] == pytest.approx(0.035)
        assert "researcher" in summary["by_agent"]
        assert "writer" in summary["by_agent"]

    async def test_get_run_agent_ids(self, client):
        resp = await client.get("/api/runs/run_0")
        data = resp.json()
        assert set(data["agent_ids"]) == {"researcher", "writer"}

    async def test_get_nonexistent_run(self, client):
        resp = await client.get("/api/runs/nonexistent")
        assert resp.status_code == 404


# ---- Run Events ----

class TestRunEvents:
    async def test_get_run_events(self, client):
        resp = await client.get("/api/runs/run_0/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 7

    async def test_filter_events_by_type(self, client):
        resp = await client.get("/api/runs/run_0/events?event_type=cost_update")
        data = resp.json()
        assert data["count"] == 2
        assert all(e["type"] == "cost_update" for e in data["events"])

    async def test_filter_events_by_agent(self, client):
        resp = await client.get("/api/runs/run_0/events?agent_id=researcher")
        data = resp.json()
        assert data["count"] >= 3
        assert all(e["agent_id"] == "researcher" for e in data["events"])

    async def test_events_pagination(self, client):
        resp = await client.get("/api/runs/run_0/events?limit=3")
        data = resp.json()
        assert data["count"] == 3

    async def test_events_for_empty_run(self, client):
        resp = await client.get("/api/runs/run_1/events")
        data = resp.json()
        assert data["count"] == 0


# ---- Delete Run ----

class TestDeleteRun:
    async def test_delete_existing(self, client):
        resp = await client.delete("/api/runs/run_0")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify deleted
        resp2 = await client.get("/api/runs/run_0")
        assert resp2.status_code == 404

    async def test_delete_nonexistent(self, client):
        resp = await client.delete("/api/runs/nonexistent")
        assert resp.status_code == 404


# ---- Export ----

class TestExportRun:
    async def test_export_existing(self, client):
        resp = await client.get("/api/runs/run_0/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 1
        assert data["run"]["id"] == "run_0"
        assert len(data["events"]) == 7

    async def test_export_nonexistent(self, client):
        resp = await client.get("/api/runs/nonexistent/export")
        assert resp.status_code == 404


# ---- Import ----

class TestImportRun:
    async def test_import_new_run(self, client):
        # First export a run
        export_resp = await client.get("/api/runs/run_0/export")
        export_data = export_resp.json()

        # Modify ID to create a new import
        export_data["run"]["id"] = "imported_run"
        export_data["run"]["name"] = "Imported Run"
        for evt in export_data["events"]:
            evt["run_id"] = "imported_run"
            evt["id"] = "imp_" + evt["id"]

        resp = await client.post("/api/runs/import", json=export_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] is True
        assert data["run_id"] == "imported_run"
        assert data["event_count"] == 7

        # Verify the imported run exists
        verify = await client.get("/api/runs/imported_run")
        assert verify.status_code == 200
        assert verify.json()["run"]["name"] == "Imported Run"

    async def test_import_duplicate_rejected(self, client):
        export_resp = await client.get("/api/runs/run_0/export")
        export_data = export_resp.json()

        # Try to import with same ID — should be 409
        resp = await client.post("/api/runs/import", json=export_data)
        assert resp.status_code == 409

    async def test_import_invalid_format(self, client):
        resp = await client.post("/api/runs/import", json={"foo": "bar"})
        assert resp.status_code == 400


# ---- Agent Detail API ----

class TestAgentEvents:
    async def test_get_agent_events(self, client):
        resp = await client.get("/api/agents/researcher/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 3

    async def test_agent_events_empty(self, client):
        resp = await client.get("/api/agents/nonexistent/events")
        data = resp.json()
        assert data["count"] == 0


class TestAgentStats:
    async def test_researcher_stats(self, client):
        resp = await client.get("/api/agents/researcher/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "researcher"
        assert data["task_count"] == 1  # 1 active status event
        assert data["total_cost"] == pytest.approx(0.015)
        assert data["total_tokens_in"] == 500
        assert data["total_tokens_out"] == 200
        assert data["messages_sent"] == 1  # 1 message_flow event
        assert "writer" in data["communication_partners"]

    async def test_writer_stats(self, client):
        resp = await client.get("/api/agents/writer/stats")
        data = resp.json()
        assert data["total_cost"] == pytest.approx(0.02)
        assert data["error_count"] == 1  # 1 error event

    async def test_nonexistent_agent_stats(self, client):
        resp = await client.get("/api/agents/nonexistent/stats")
        data = resp.json()
        assert data["task_count"] == 0
        assert data["total_cost"] == 0
        assert data["event_count"] == 0
