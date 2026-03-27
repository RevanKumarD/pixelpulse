"""PixelPulse Event Protocol — the event types and envelope format.

All events flow through this protocol. Events are simple dicts with a
required ``type`` field and optional ``payload``, ``correlation``, and
``source`` fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

# ---- Event Types ----

AGENT_STARTED = "agent.started"
AGENT_COMPLETED = "agent.completed"
AGENT_ERROR = "agent.error"
AGENT_THINKING = "agent.thinking"
MESSAGE_SENT = "message.sent"
PIPELINE_STAGE_ENTERED = "pipeline.stage_entered"
PIPELINE_STAGE_EXITED = "pipeline.stage_exited"
ARTIFACT_CREATED = "artifact.created"
COST_UPDATE = "cost.update"
RUN_STARTED = "run.started"
RUN_COMPLETED = "run.completed"

EVENT_TYPES: frozenset[str] = frozenset({
    AGENT_STARTED,
    AGENT_COMPLETED,
    AGENT_ERROR,
    AGENT_THINKING,
    MESSAGE_SENT,
    PIPELINE_STAGE_ENTERED,
    PIPELINE_STAGE_EXITED,
    ARTIFACT_CREATED,
    COST_UPDATE,
    RUN_STARTED,
    RUN_COMPLETED,
})

# ---- Dashboard-internal types (mapped from protocol types) ----
# These match what the JS dashboard expects from the PixelPulse EventBus

DASHBOARD_TYPE_MAP: dict[str, str] = {
    AGENT_STARTED: "agent_status",
    AGENT_COMPLETED: "agent_status",
    AGENT_ERROR: "error",
    AGENT_THINKING: "agent_status",
    MESSAGE_SENT: "message_flow",
    PIPELINE_STAGE_ENTERED: "pipeline_progress",
    PIPELINE_STAGE_EXITED: "pipeline_progress",
    ARTIFACT_CREATED: "artifact_event",
    COST_UPDATE: "cost_update",
    RUN_STARTED: "pipeline_progress",
    RUN_COMPLETED: "pipeline_progress",
}


def create_event(
    event_type: str,
    payload: dict | None = None,
    run_id: str = "",
    source_framework: str = "",
) -> dict:
    """Create a fully-formed PixelPulse event dict."""
    return {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": event_type,
        "timestamp": _utc_now(),
        "source": {
            "framework": source_framework,
        },
        "correlation": {
            "run_id": run_id,
        },
        "payload": payload or {},
    }


def to_dashboard_event(event: dict) -> dict:
    """Convert a PixelPulse protocol event to the dashboard WebSocket format.

    The JS dashboard expects events in the PixelPulse format::

        {"type": "agent_status", "timestamp": "...", "payload": {...}}

    This function maps PixelPulse event types to dashboard types and
    reshapes the payload as needed.
    """
    event_type = event.get("type", "")
    payload = event.get("payload", {})
    timestamp = event.get("timestamp", _utc_now())

    dashboard_type = DASHBOARD_TYPE_MAP.get(event_type)
    if not dashboard_type:
        return {"type": event_type, "timestamp": timestamp, "payload": payload}

    dashboard_payload = dict(payload)

    # Map protocol fields to dashboard expectations
    if event_type == AGENT_STARTED:
        dashboard_payload["status"] = "active"
        dashboard_payload["current_task"] = payload.get("task", "")
        dashboard_payload["thinking"] = payload.get("task", "")
    elif event_type == AGENT_COMPLETED:
        dashboard_payload["status"] = "idle"
        dashboard_payload["thinking"] = payload.get("output", "")[:120] + (
            "..." if len(payload.get("output", "")) > 120 else ""
        )
    elif event_type == AGENT_ERROR:
        dashboard_payload["agent_id"] = payload.get("agent_id", "")
        dashboard_payload["error"] = payload.get("error", "Unknown error")
    elif event_type == AGENT_THINKING:
        dashboard_payload["status"] = "active"
        dashboard_payload["thinking"] = payload.get("thought", "")
    elif event_type == MESSAGE_SENT:
        dashboard_payload["from"] = payload.get("from", "")
        dashboard_payload["to"] = payload.get("to", "")
        dashboard_payload["content"] = payload.get("content", "")
        dashboard_payload["tag"] = payload.get("tag", "data")
    elif event_type in (PIPELINE_STAGE_ENTERED, PIPELINE_STAGE_EXITED):
        dashboard_payload["stage"] = payload.get("stage", "")
        dashboard_payload["status"] = (
            "active" if event_type == PIPELINE_STAGE_ENTERED else "completed"
        )
        dashboard_payload["message"] = payload.get("message", f"Stage: {payload.get('stage', '')}")
    elif event_type == COST_UPDATE:
        pass  # payload already has agent_id, cost, etc.
    elif event_type == RUN_STARTED:
        dashboard_payload["stage"] = "started"
        dashboard_payload["status"] = "active"
        dashboard_payload["message"] = (
            f"Run started: {payload.get('name', payload.get('run_id', ''))}"
        )
    elif event_type == RUN_COMPLETED:
        dashboard_payload["stage"] = "completed"
        dashboard_payload["status"] = payload.get("status", "completed")
        dashboard_payload["message"] = f"Run {payload.get('status', 'completed')}"

    return {
        "type": dashboard_type,
        "timestamp": timestamp,
        "payload": dashboard_payload,
    }


def validate_event(event: dict) -> list[str]:
    """Validate an event dict. Returns a list of error strings (empty = valid)."""
    errors = []
    if "type" not in event:
        errors.append("Missing 'type' field")
    elif event["type"] not in EVENT_TYPES:
        errors.append(f"Unknown event type: {event['type']}")
    return errors


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
