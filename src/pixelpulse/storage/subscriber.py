"""EventBus subscriber that auto-persists events to SQLite.

The StorageSubscriber listens for events on the bus and:
- Creates run records when run.started events arrive
- Saves every event to the events table
- Updates run status/totals when run.completed events arrive
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from pixelpulse.storage.db import Database
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
from pixelpulse.storage.run_repo import RunRepository

logger = logging.getLogger(__name__)

# Map dashboard types back to protocol types for storage
_DASHBOARD_TO_PROTOCOL = {
    "agent_status": "agent.status",
    "error": "agent.error",
    "message_flow": "message.sent",
    "pipeline_progress": "pipeline.progress",
    "artifact_event": "artifact.created",
    "cost_update": "cost.update",
}


class StorageSubscriber:
    """Subscribes to EventBus and persists events to SQLite.

    Usage::

        db = Database("pixelpulse_runs.db")
        await db.connect()
        subscriber = StorageSubscriber(db)
        await subscriber.attach(bus)

    Events are stored as-is (dashboard format). A "default" run is
    auto-created if events arrive without an explicit run.started.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._runs = RunRepository(db)
        self._events = EventRepository(db)
        self._current_run_id: str | None = None
        self._agents_seen: set[str] = set()
        self._cost_accumulator: float = 0.0
        self._tokens_in_accumulator: int = 0
        self._tokens_out_accumulator: int = 0

    @property
    def current_run_id(self) -> str | None:
        return self._current_run_id

    async def attach(self, bus) -> None:
        """Subscribe to the event bus."""
        await bus.subscribe(self._on_event)

    async def detach(self, bus) -> None:
        """Unsubscribe from the event bus."""
        await bus.unsubscribe(self._on_event)

    async def _on_event(self, event: dict) -> None:
        """Handle an incoming event from the bus."""
        try:
            await self._process_event(event)
        except Exception:
            logger.exception("StorageSubscriber failed to process event")

    async def _process_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        payload = event.get("payload", {})
        timestamp = event.get("timestamp", _utc_now())

        # Detect run lifecycle from pipeline_progress events
        if event_type == "pipeline_progress":
            stage = payload.get("stage", "")
            status = payload.get("status", "")

            if stage == "started" and status == "active":
                await self._handle_run_started(payload, timestamp)
                return

            if stage == "completed":
                await self._handle_run_completed(payload, timestamp)
                return

        # Ensure we have a run to attach events to
        if self._current_run_id is None:
            await self._create_default_run(timestamp)

        # Track agents
        agent_id = self._extract_agent_id(event_type, payload)
        if agent_id:
            self._agents_seen.add(agent_id)

        # Track costs
        if event_type == "cost_update":
            self._cost_accumulator += payload.get("cost", 0)
            self._tokens_in_accumulator += payload.get("tokens_in", 0)
            self._tokens_out_accumulator += payload.get("tokens_out", 0)

        # Persist the event
        record = EventRecord(
            id=f"evt_{uuid4().hex[:16]}",
            run_id=self._current_run_id,
            type=event_type,
            timestamp=timestamp,
            source_framework=_DASHBOARD_TO_PROTOCOL.get(event_type, event_type),
            payload=payload,
            agent_id=agent_id,
        )
        await self._events.create(record)
        await self._runs.increment_event_count(self._current_run_id)

    async def _handle_run_started(self, payload: dict, timestamp: str) -> None:
        """Handle a run.started event."""
        message = payload.get("message", "")
        # Extract run name from "Run started: <name>"
        name = message.replace("Run started: ", "").strip() if message else ""
        run_id = f"run_{uuid4().hex[:12]}"

        run = RunRecord(
            id=run_id,
            name=name,
            status=RunStatus.ACTIVE,
            started_at=timestamp,
        )
        await self._runs.create(run)
        self._current_run_id = run_id
        self._agents_seen.clear()
        self._cost_accumulator = 0.0
        self._tokens_in_accumulator = 0
        self._tokens_out_accumulator = 0
        logger.info("Run started: %s (%s)", name, run_id)

    async def _handle_run_completed(self, payload: dict, timestamp: str) -> None:
        """Handle a run.completed event."""
        if self._current_run_id is None:
            return

        status_str = payload.get("status", "completed")
        if status_str == "failed":
            status = RunStatus.FAILED
        elif status_str == "canceled":
            status = RunStatus.CANCELED
        else:
            status = RunStatus.COMPLETED

        await self._runs.update_status(
            self._current_run_id,
            status=status,
            completed_at=timestamp,
            total_cost=self._cost_accumulator,
            total_tokens_in=self._tokens_in_accumulator,
            total_tokens_out=self._tokens_out_accumulator,
        )
        await self._runs.update_agent_count(
            self._current_run_id, len(self._agents_seen)
        )
        logger.info("Run completed: %s (status=%s)", self._current_run_id, status)
        self._current_run_id = None

    async def _create_default_run(self, timestamp: str) -> None:
        """Create a default run for events that arrive without an explicit run.started."""
        run_id = f"run_{uuid4().hex[:12]}"
        run = RunRecord(
            id=run_id,
            name="Default Session",
            status=RunStatus.ACTIVE,
            started_at=timestamp,
        )
        await self._runs.create(run)
        self._current_run_id = run_id
        self._agents_seen.clear()
        self._cost_accumulator = 0.0
        self._tokens_in_accumulator = 0
        self._tokens_out_accumulator = 0

    @staticmethod
    def _extract_agent_id(event_type: str, payload: dict) -> str:
        """Extract agent_id from different event type payloads."""
        if event_type in ("agent_status", "cost_update", "error", "artifact_event"):
            return payload.get("agent_id", "")
        if event_type == "message_flow":
            return payload.get("from", "")
        return ""


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
