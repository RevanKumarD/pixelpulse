"""FastAPI server that serves the pixel-art dashboard and handles WebSocket events.

The server provides:
- Static file serving for the dashboard frontend
- WebSocket endpoint for real-time event streaming
- REST API for configuration, event history, and run management
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pixelpulse.bus import get_event_bus, set_main_loop
from pixelpulse.otel import parse_otlp_spans, span_to_events
from pixelpulse.protocol import to_dashboard_event

if TYPE_CHECKING:
    from pixelpulse.config import AgentConfig, TeamConfig

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    agents: dict[str, AgentConfig],
    teams: dict[str, TeamConfig],
    pipeline_stages: list[str] | None = None,
    title: str = "PixelPulse",
    db_path: str | Path | None = None,
) -> FastAPI:
    """Create the FastAPI application with dashboard and WebSocket support."""

    # ---- State ----
    bus = get_event_bus()
    _storage = {"db": None, "subscriber": None, "runs": None, "events": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        set_main_loop()
        # Initialize storage if db_path is provided
        if db_path is not None:
            from pixelpulse.storage.db import Database
            from pixelpulse.storage.event_repo import EventRepository
            from pixelpulse.storage.run_repo import RunRepository
            from pixelpulse.storage.subscriber import StorageSubscriber

            db = Database(db_path)
            await db.connect()
            _storage["db"] = db
            _storage["runs"] = RunRepository(db)
            _storage["events"] = EventRepository(db)
            _storage["subscriber"] = StorageSubscriber(db)
            await _storage["subscriber"].attach(bus)
            logger.info("PixelPulse storage enabled: %s", db_path)
        yield
        # Cleanup storage
        if _storage["subscriber"] is not None:
            await _storage["subscriber"].detach(bus)
        if _storage["db"] is not None:
            await _storage["db"].close()

    app = FastAPI(title=title, docs_url=None, redoc_url=None, lifespan=lifespan)

    # ---- Dashboard ----

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    # Mount static files AFTER explicit routes
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---- Config API (dashboard fetches this on load) ----

    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        """Return agent/team/pipeline configuration for the dashboard.

        The dashboard's state.js expects:
        - teams: { teamId: { label, role, icon, color, agents: [...] } }
        - agent_roles: { agentId: "role description" }
        - pipeline_stages: ["stage1", "stage2", ...]
        - stage_to_team: { stageName: teamId | null }
        """
        teams_data = {}
        for team_id, tc in teams.items():
            team_agents = [
                name for name, ac in agents.items() if ac.team == team_id
            ]
            teams_data[team_id] = {
                "label": tc.label or team_id.replace("_", " ").title(),
                "color": tc.color,
                "icon": tc.icon,
                "role": tc.role,
                "agents": team_agents,
            }

        # agent_roles: flat mapping of agent_id → role description
        agent_roles = {name: ac.role for name, ac in agents.items()}

        # stage_to_team: map each pipeline stage to a team (or null)
        # Convention: if a stage name matches a team ID, map it automatically
        stage_to_team = {}
        for stage in (pipeline_stages or []):
            if stage in teams:
                stage_to_team[stage] = stage
            else:
                # Try to find a team whose agents are relevant to this stage
                stage_to_team[stage] = None

        return JSONResponse({
            "title": title,
            "teams": teams_data,
            "agents": {
                name: {"role": ac.role, "team": ac.team, "sprite": ac.sprite}
                for name, ac in agents.items()
            },
            "agent_roles": agent_roles,
            "pipeline_stages": pipeline_stages or [],
            "stage_to_team": stage_to_team,
        })

    # ---- Event History ----

    @app.get("/api/events")
    async def get_events() -> JSONResponse:
        history = bus.get_history()
        dashboard_events = [to_dashboard_event(e) for e in history[-50:]]
        return JSONResponse(dashboard_events)

    # ---- Health ----

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": "0.1.0"})

    # ---- Event Ingestion (for external emitters) ----

    @app.post("/api/events/ingest")
    async def ingest_event(event: dict) -> JSONResponse:
        dashboard_event = to_dashboard_event(event)
        await bus.emit(dashboard_event)
        return JSONResponse({"accepted": 1})

    # ---- OTLP JSON Trace Ingestion ----

    @app.post("/v1/traces")
    async def ingest_traces(body: dict) -> JSONResponse:
        """Accept OTLP JSON traces and convert to PixelPulse dashboard events.

        This endpoint allows ANY OpenTelemetry-instrumented system to send
        traces to PixelPulse without the Python SDK. Configure your OTel
        exporter to point at ``http://<host>:<port>/v1/traces``.

        The expected body follows the OTLP JSON format::

            {
              "resourceSpans": [{
                "scopeSpans": [{
                  "spans": [{ "name": "...", "attributes": [...], ... }]
                }]
              }]
            }
        """
        spans = parse_otlp_spans(body)
        accepted = 0
        for span in spans:
            pp_events = span_to_events(span)
            for event in pp_events:
                dashboard_event = to_dashboard_event(event)
                await bus.emit(dashboard_event)
                accepted += 1
        return JSONResponse({"accepted": accepted})

    # ---- Claude Code Hook Receiver ----

    _claude_code_adapter = None

    @app.post("/hooks/claude-code")
    async def claude_code_hook(event: dict) -> JSONResponse:
        """Receive Claude Code hook events and translate to PixelPulse events.

        Configure Claude Code to POST to this endpoint by adding HTTP hooks
        to ``.claude/settings.json``. Use ``adapter.generate_hooks_config()``
        to generate the config.
        """
        nonlocal _claude_code_adapter
        if _claude_code_adapter is None:
            from pixelpulse.adapters.claude_code import ClaudeCodeAdapter

            # Create a minimal PixelPulse-like emitter that uses the bus
            class _BusEmitter:
                def __init__(self, bus_ref, agents_ref):
                    self._bus = bus_ref
                    self._agents = agents_ref
                    self._framework = "claude_code"

                def run_started(self, run_id, name=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "run_started", "run_id": run_id, "name": name
                        }))
                    )

                def run_completed(self, run_id, status="completed", total_cost=0):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "run_completed", "run_id": run_id,
                            "status": status, "total_cost": total_cost,
                        }))
                    )

                def agent_started(self, agent, task=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "agent_started", "agent": agent, "task": task
                        }))
                    )

                def agent_thinking(self, agent, thought=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "agent_thinking", "agent": agent, "thought": thought
                        }))
                    )

                def agent_completed(self, agent, output=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "agent_completed", "agent": agent, "output": output
                        }))
                    )

                def agent_error(self, agent, error=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "agent_error", "agent": agent, "error": error
                        }))
                    )

                def artifact_created(self, agent, artifact_type="", content=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "artifact_created", "agent": agent,
                            "artifact_type": artifact_type, "content": content,
                        }))
                    )

                def cost_update(self, agent, cost=0, tokens_in=0, tokens_out=0, model=""):
                    asyncio.get_event_loop().create_task(
                        self._bus.emit(to_dashboard_event({
                            "type": "cost_update", "agent": agent, "cost": cost,
                            "tokens_in": tokens_in, "tokens_out": tokens_out, "model": model,
                        }))
                    )

            emitter = _BusEmitter(bus, agents)
            _claude_code_adapter = ClaudeCodeAdapter(emitter)
            _claude_code_adapter.instrument()

        response = _claude_code_adapter.on_hook_event(event)
        return JSONResponse(response)

    # ---- Run History API ----

    @app.get("/api/runs")
    async def list_runs(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        status: str | None = Query(None),
    ) -> JSONResponse:
        """List saved runs, newest first."""
        if _storage["runs"] is None:
            return JSONResponse({"runs": [], "total": 0, "storage_enabled": False})
        runs = await _storage["runs"].list_all(limit=limit, offset=offset, status=status)
        total = await _storage["runs"].count(status=status)
        return JSONResponse({
            "runs": [r.to_dict() for r in runs],
            "total": total,
            "storage_enabled": True,
        })

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> JSONResponse:
        """Get a run by ID with summary stats."""
        if _storage["runs"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)
        run = await _storage["runs"].get(run_id)
        if run is None:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        cost_summary = await _storage["events"].get_cost_summary(run_id)
        agent_ids = await _storage["events"].get_agent_ids_for_run(run_id)
        return JSONResponse({
            "run": run.to_dict(),
            "cost_summary": cost_summary,
            "agent_ids": agent_ids,
        })

    @app.get("/api/runs/{run_id}/events")
    async def get_run_events(
        run_id: str,
        event_type: str | None = Query(None),
        agent_id: str | None = Query(None),
        limit: int = Query(1000, ge=1, le=10000),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """Get events for a run (for replay or inspection)."""
        if _storage["events"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)
        events = await _storage["events"].list_by_run(
            run_id, event_type=event_type, agent_id=agent_id,
            limit=limit, offset=offset,
        )
        return JSONResponse({
            "events": [e.to_dict() for e in events],
            "count": len(events),
        })

    @app.delete("/api/runs/{run_id}")
    async def delete_run(run_id: str) -> JSONResponse:
        """Delete a run and all its events."""
        if _storage["runs"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)
        deleted = await _storage["runs"].delete(run_id)
        if not deleted:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse({"deleted": True})

    @app.get("/api/runs/{run_id}/export")
    async def export_run(run_id: str) -> JSONResponse:
        """Export a run with all events as JSON."""
        if _storage["runs"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)
        export = await _storage["runs"].export_run(run_id)
        if export is None:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse(export)

    @app.post("/api/runs/import")
    async def import_run(body: dict) -> JSONResponse:
        """Import a run from exported JSON."""
        if _storage["runs"] is None or _storage["events"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)

        from pixelpulse.storage.models import EventRecord, RunRecord

        run_data = body.get("run")
        events_data = body.get("events", [])
        if not run_data or "id" not in run_data:
            return JSONResponse({"error": "Invalid import format"}, status_code=400)

        # Check if run already exists
        existing = await _storage["runs"].get(run_data["id"])
        if existing is not None:
            return JSONResponse({"error": "Run already exists"}, status_code=409)

        run = RunRecord(
            id=run_data["id"],
            name=run_data.get("name", ""),
            status=run_data.get("status", "completed"),
            started_at=run_data.get("started_at", ""),
            completed_at=run_data.get("completed_at", ""),
            total_cost=run_data.get("total_cost", 0),
            total_tokens_in=run_data.get("total_tokens_in", 0),
            total_tokens_out=run_data.get("total_tokens_out", 0),
            agent_count=run_data.get("agent_count", 0),
            event_count=run_data.get("event_count", 0),
            metadata=run_data.get("metadata", {}),
        )
        await _storage["runs"].create(run)

        for evt_data in events_data:
            event = EventRecord(
                id=evt_data["id"],
                run_id=evt_data["run_id"],
                type=evt_data["type"],
                timestamp=evt_data["timestamp"],
                source_framework=evt_data.get("source_framework", ""),
                payload=evt_data.get("payload", {}),
                agent_id=evt_data.get("agent_id", ""),
            )
            await _storage["events"].create(event)

        return JSONResponse({"imported": True, "run_id": run.id, "event_count": len(events_data)})

    # ---- Agent Detail API ----

    @app.get("/api/agents/{agent_id}/events")
    async def get_agent_events(
        agent_id: str,
        run_id: str | None = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """Get events for a specific agent."""
        if _storage["events"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)
        events = await _storage["events"].list_by_agent(
            agent_id, run_id=run_id, limit=limit, offset=offset,
        )
        return JSONResponse({
            "events": [e.to_dict() for e in events],
            "count": len(events),
        })

    @app.get("/api/agents/{agent_id}/stats")
    async def get_agent_stats(agent_id: str, run_id: str | None = Query(None)) -> JSONResponse:
        """Get computed stats for an agent."""
        if _storage["events"] is None:
            return JSONResponse({"error": "Storage not enabled"}, status_code=503)
        events = await _storage["events"].list_by_agent(agent_id, run_id=run_id)

        task_count = sum(1 for e in events if e.type == "agent_status"
                         and e.payload.get("status") == "active")
        error_count = sum(1 for e in events if e.type == "error")
        total_cost = sum(e.payload.get("cost", 0) for e in events if e.type == "cost_update")
        total_tokens_in = sum(
            e.payload.get("tokens_in", 0) for e in events if e.type == "cost_update"
        )
        total_tokens_out = sum(
            e.payload.get("tokens_out", 0) for e in events if e.type == "cost_update"
        )
        messages_sent = sum(1 for e in events if e.type == "message_flow")

        # Find communication partners
        partners: dict[str, int] = {}
        for e in events:
            if e.type == "message_flow":
                to_agent = e.payload.get("to", "")
                if to_agent:
                    partners[to_agent] = partners.get(to_agent, 0) + 1

        return JSONResponse({
            "agent_id": agent_id,
            "task_count": task_count,
            "error_count": error_count,
            "total_cost": total_cost,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "messages_sent": messages_sent,
            "communication_partners": partners,
            "event_count": len(events),
        })

    # ---- WebSocket ----

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        logger.info("Dashboard WebSocket connected")

        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)

        async def _subscriber(event: dict) -> None:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop oldest if dashboard can't keep up

        await bus.subscribe(_subscriber)

        # Send recent history as initial state
        history = bus.get_history()
        if history:
            try:
                await ws.send_json(history[-20:])
            except Exception:
                pass

        try:
            # Batch events for efficiency
            while True:
                # Wait for at least one event
                event = await queue.get()
                batch = [event]

                # Drain any additional queued events
                while not queue.empty() and len(batch) < 20:
                    try:
                        batch.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                await ws.send_json(batch if len(batch) > 1 else batch[0])
        except WebSocketDisconnect:
            logger.info("Dashboard WebSocket disconnected")
        except Exception as exc:
            logger.error("WebSocket error: %s", exc)
        finally:
            await bus.unsubscribe(_subscriber)

    return app
