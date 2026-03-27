"""PixelPulse — the main entry point for the SDK.

This module provides the :class:`PixelPulse` class, which is the primary
interface for setting up and running the pixel-art agent dashboard.
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Any

import uvicorn

from pixelpulse.bus import emit_sync, get_event_bus
from pixelpulse.config import (
    AgentConfig,
    TeamConfig,
    normalize_agents,
    normalize_teams,
)
from pixelpulse.protocol import (
    AGENT_COMPLETED,
    AGENT_ERROR,
    AGENT_STARTED,
    AGENT_THINKING,
    ARTIFACT_CREATED,
    COST_UPDATE,
    MESSAGE_SENT,
    PIPELINE_STAGE_ENTERED,
    PIPELINE_STAGE_EXITED,
    RUN_COMPLETED,
    RUN_STARTED,
    create_event,
    to_dashboard_event,
)

logger = logging.getLogger(__name__)


class PixelPulse:
    """Real-time pixel-art dashboard for multi-agent systems.

    Quick start::

        from pixelpulse import PixelPulse

        pp = PixelPulse(
            agents={
                "researcher": {"team": "research", "role": "Finds information"},
                "writer": {"team": "content", "role": "Writes articles"},
            },
            teams={
                "research": {"label": "Research", "color": "#00d4ff"},
                "content": {"label": "Content", "color": "#ff6ec7"},
            },
        )
        pp.serve(port=8765)

    Then emit events from your agent code::

        pp.agent_started("researcher", task="Searching for trends")
        pp.agent_message("researcher", "writer", content="Found 5 trends")
        pp.agent_completed("researcher", output="Full research output here")
    """

    def __init__(
        self,
        agents: dict[str, AgentConfig | dict],
        teams: dict[str, TeamConfig | dict] | None = None,
        pipeline: list[str] | None = None,
        title: str = "PixelPulse",
        theme: str = "dark",
        port: int = 8765,
        storage: bool = True,
        db_path: str | None = None,
    ) -> None:
        self._agents = normalize_agents(agents)
        self._teams = normalize_teams(teams)
        self._pipeline = pipeline or []
        self._title = title
        self._theme = theme
        self._port = port
        self._bus = get_event_bus()
        self._app = None
        self._framework: str = ""
        self._adapters: dict[str, Any] = {}
        self._storage_enabled = storage
        self._db_path = db_path or "pixelpulse_runs.db"

        # Auto-create default team for agents without explicit team assignment
        assigned_teams = {ac.team for ac in self._agents.values()}
        for team_id in assigned_teams:
            if team_id not in self._teams:
                self._teams[team_id] = TeamConfig(
                    label=team_id.replace("_", " ").replace("-", " ").title(),
                )

    @property
    def agents(self) -> dict[str, AgentConfig]:
        return dict(self._agents)

    @property
    def teams(self) -> dict[str, TeamConfig]:
        return dict(self._teams)

    # ---- Server Lifecycle ----

    def serve(self, port: int | None = None, open_browser: bool = True) -> None:
        """Start the dashboard server (blocking).

        This starts a uvicorn server that serves the pixel-art dashboard
        and opens it in the default browser.
        """
        port = port or self._port
        self._app = self._create_app()

        if open_browser:
            # Open browser after a short delay to let server start
            timer = threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}"))
            timer.daemon = True
            timer.start()

        logger.info("PixelPulse dashboard starting at http://localhost:%d", port)
        uvicorn.run(self._app, host="0.0.0.0", port=port, log_level="warning")

    async def serve_async(self, port: int | None = None) -> None:
        """Start the dashboard server (async, non-blocking)."""
        port = port or self._port
        self._app = self._create_app()

        config = uvicorn.Config(self._app, host="0.0.0.0", port=port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()

    def _create_app(self):
        from pixelpulse.server import create_app

        return create_app(
            agents=self._agents,
            teams=self._teams,
            pipeline_stages=self._pipeline,
            title=self._title,
            db_path=self._db_path if self._storage_enabled else None,
        )

    # ---- Event Emission ----

    def emit(self, event: dict) -> None:
        """Emit a raw PixelPulse event.

        The event is converted to the dashboard format and broadcast
        to all connected WebSocket clients.
        """
        dashboard_event = to_dashboard_event(event)
        emit_sync(dashboard_event)

    def _emit(self, event_type: str, payload: dict) -> None:
        """Internal: create and emit a protocol event."""
        event = create_event(event_type, payload, source_framework=self._framework)
        self.emit(event)

    # ---- Convenience Emitters ----

    def agent_started(self, agent_id: str, task: str = "", **kw: Any) -> None:
        """Signal that an agent has started working."""
        self._emit(AGENT_STARTED, {"agent_id": agent_id, "task": task, **kw})

    def agent_completed(self, agent_id: str, output: str = "", **kw: Any) -> None:
        """Signal that an agent has finished its work."""
        self._emit(AGENT_COMPLETED, {"agent_id": agent_id, "output": output, **kw})

    def agent_error(self, agent_id: str, error: str = "", **kw: Any) -> None:
        """Signal that an agent encountered an error."""
        self._emit(AGENT_ERROR, {"agent_id": agent_id, "error": error, **kw})

    def agent_thinking(self, agent_id: str, thought: str = "", **kw: Any) -> None:
        """Signal an intermediate reasoning step from an agent."""
        self._emit(AGENT_THINKING, {"agent_id": agent_id, "thought": thought, **kw})

    def agent_message(
        self,
        from_id: str,
        to_id: str,
        content: str = "",
        tag: str = "data",
        **kw: Any,
    ) -> None:
        """Signal a message between two agents."""
        self._emit(MESSAGE_SENT, {
            "from": from_id, "to": to_id, "content": content, "tag": tag, **kw
        })

    def stage_entered(self, stage: str, run_id: str = "", **kw: Any) -> None:
        """Signal that a pipeline stage has been entered."""
        self._emit(PIPELINE_STAGE_ENTERED, {"stage": stage, "run_id": run_id, **kw})

    def stage_exited(self, stage: str, run_id: str = "", **kw: Any) -> None:
        """Signal that a pipeline stage has been exited."""
        self._emit(PIPELINE_STAGE_EXITED, {"stage": stage, "run_id": run_id, **kw})

    def artifact_created(
        self,
        agent_id: str,
        artifact_type: str = "text",
        content: str = "",
        uri: str = "",
        **kw: Any,
    ) -> None:
        """Signal that an agent produced an artifact."""
        self._emit(ARTIFACT_CREATED, {
            "agent_id": agent_id,
            "artifact_type": artifact_type,
            "content": content,
            "uri": uri,
            **kw,
        })

    def cost_update(
        self,
        agent_id: str,
        cost: float = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        model: str = "",
        **kw: Any,
    ) -> None:
        """Report token usage and cost for an agent."""
        self._emit(COST_UPDATE, {
            "agent_id": agent_id,
            "cost": cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
            **kw,
        })

    def run_started(self, run_id: str, name: str = "", **kw: Any) -> None:
        """Signal the start of a pipeline run."""
        self._emit(RUN_STARTED, {"run_id": run_id, "name": name, **kw})

    def run_completed(
        self, run_id: str, status: str = "completed", total_cost: float = 0, **kw: Any
    ) -> None:
        """Signal the completion of a pipeline run."""
        self._emit(RUN_COMPLETED, {
            "run_id": run_id, "status": status, "total_cost": total_cost, **kw
        })

    # ---- Framework Adapter ----

    def adapter(self, framework: str) -> Any:
        """Get a framework-specific adapter.

        Supported frameworks: ``crewai``, ``langgraph``, ``openai``, ``autogen``,
        ``claude_code``, ``generic``
        """
        self._framework = framework

        if framework == "crewai":
            from pixelpulse.adapters.crewai import CrewAIAdapter
            return CrewAIAdapter(self)
        elif framework == "langgraph":
            from pixelpulse.adapters.langgraph import LangGraphAdapter
            return LangGraphAdapter(self)
        elif framework == "openai":
            from pixelpulse.adapters.openai_agents import OpenAIAgentsAdapter
            return OpenAIAgentsAdapter(self)
        elif framework == "autogen":
            from pixelpulse.adapters.autogen import AutoGenAdapter
            return AutoGenAdapter(self)
        elif framework == "claude_code":
            from pixelpulse.adapters.claude_code import ClaudeCodeAdapter
            return ClaudeCodeAdapter(self)
        elif framework == "generic":
            from pixelpulse.adapters.generic import GenericAdapter
            return GenericAdapter(self)
        else:
            raise ValueError(
                f"Unknown framework: {framework}. "
                f"Supported: crewai, langgraph, openai, autogen, claude_code, generic"
            )

    def auto_instrument(self) -> dict[str, bool]:
        """Auto-detect installed agent frameworks and instrument them.

        Tries to import each supported framework package. When a framework is
        found, its adapter is created and stored in ``self._adapters``.  This
        method never raises — a missing package simply records ``False``.

        Returns:
            A mapping of framework name to whether it was detected and
            instrumented, e.g. ``{"crewai": True, "langgraph": False, ...}``.

        Example::

            pp = PixelPulse(agents={...})
            detected = pp.auto_instrument()
            # {"crewai": False, "langgraph": True, "openai": False, "autogen": False}
        """
        # (adapter_name, package_to_import)
        _frameworks = [
            ("crewai", "crewai"),
            ("langgraph", "langgraph"),
            ("openai", "agents"),
            ("autogen", "autogen"),
        ]

        results: dict[str, bool] = {}
        for adapter_name, package_name in _frameworks:
            try:
                __import__(package_name)
                self._adapters[adapter_name] = self.adapter(adapter_name)
                results[adapter_name] = True
                logger.info("Auto-instrumented: %s", adapter_name)
            except ImportError:
                results[adapter_name] = False

        return results
