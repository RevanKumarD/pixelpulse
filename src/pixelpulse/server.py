"""FastAPI server that serves the pixel-art dashboard and handles WebSocket events.

The server provides:
- Static file serving for the dashboard frontend
- WebSocket endpoint for real-time event streaming
- REST API for configuration and event history
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pixelpulse.bus import EventBus, get_event_bus, set_main_loop
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
) -> FastAPI:
    """Create the FastAPI application with dashboard and WebSocket support."""

    # ---- State ----
    bus = get_event_bus()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        set_main_loop()
        yield

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
            "agents": {name: {"role": ac.role, "team": ac.team, "sprite": ac.sprite} for name, ac in agents.items()},
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
