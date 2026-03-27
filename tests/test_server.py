"""Tests for the PixelPulse FastAPI server."""
import pytest
from httpx import ASGITransport, AsyncClient

from pixelpulse.config import normalize_agents, normalize_teams
from pixelpulse.server import create_app


def _make_app():
    agents = normalize_agents({
        "researcher": {"team": "research", "role": "Finds info"},
        "writer": {"team": "content", "role": "Writes"},
    })
    teams = normalize_teams({
        "research": {"label": "Research", "color": "#00d4ff"},
        "content": {"label": "Content", "color": "#ff6ec7"},
    })
    return create_app(agents=agents, teams=teams, pipeline_stages=["research", "writing"])


async def _get_client():
    app = _make_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:
    async def test_returns_ok(self):
        async with await _get_client() as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "version" in data


class TestConfigEndpoint:
    async def test_returns_agents_and_teams(self):
        async with await _get_client() as client:
            resp = await client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert "agents" in data
            assert "teams" in data
            assert "researcher" in data["agents"]
            assert "writer" in data["agents"]
            assert data["agents"]["researcher"]["team"] == "research"

    async def test_returns_pipeline_stages(self):
        async with await _get_client() as client:
            resp = await client.get("/api/config")
            data = resp.json()
            assert data["pipeline_stages"] == ["research", "writing"]

    async def test_teams_include_agent_list(self):
        async with await _get_client() as client:
            resp = await client.get("/api/config")
            data = resp.json()
            assert "researcher" in data["teams"]["research"]["agents"]
            assert "writer" in data["teams"]["content"]["agents"]


class TestEventsEndpoint:
    async def test_returns_empty_list_initially(self):
        async with await _get_client() as client:
            resp = await client.get("/api/events")
            assert resp.status_code == 200
            assert resp.json() == []


class TestEventIngestion:
    async def test_ingest_event(self):
        async with await _get_client() as client:
            event = {
                "type": "agent.started",
                "payload": {"agent_id": "researcher", "task": "Testing"},
            }
            resp = await client.post("/api/events/ingest", json=event)
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 1
