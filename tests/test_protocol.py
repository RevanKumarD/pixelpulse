"""Tests for the PixelPulse event protocol."""
from pixelpulse.protocol import (
    AGENT_COMPLETED,
    AGENT_STARTED,
    AGENT_THINKING,
    COST_UPDATE,
    EVENT_TYPES,
    MESSAGE_SENT,
    RUN_STARTED,
    create_event,
    to_dashboard_event,
    validate_event,
)


class TestCreateEvent:
    def test_creates_event_with_required_fields(self):
        event = create_event(AGENT_STARTED, {"agent_id": "test"})
        assert event["type"] == AGENT_STARTED
        assert event["payload"]["agent_id"] == "test"
        assert "id" in event
        assert "timestamp" in event

    def test_includes_source_framework(self):
        event = create_event(AGENT_STARTED, {}, source_framework="crewai")
        assert event["source"]["framework"] == "crewai"

    def test_includes_run_id(self):
        event = create_event(AGENT_STARTED, {}, run_id="run_123")
        assert event["correlation"]["run_id"] == "run_123"


class TestToDashboardEvent:
    def test_agent_started_maps_to_agent_status_active(self):
        event = create_event(AGENT_STARTED, {"agent_id": "researcher", "task": "Searching"})
        dashboard = to_dashboard_event(event)
        assert dashboard["type"] == "agent_status"
        assert dashboard["payload"]["status"] == "active"
        assert dashboard["payload"]["agent_id"] == "researcher"

    def test_agent_completed_maps_to_agent_status_idle(self):
        event = create_event(AGENT_COMPLETED, {"agent_id": "researcher", "output": "Found 5 results"})
        dashboard = to_dashboard_event(event)
        assert dashboard["type"] == "agent_status"
        assert dashboard["payload"]["status"] == "idle"

    def test_message_sent_maps_to_message_flow(self):
        event = create_event(MESSAGE_SENT, {
            "from": "researcher", "to": "writer", "content": "Data ready", "tag": "data"
        })
        dashboard = to_dashboard_event(event)
        assert dashboard["type"] == "message_flow"
        assert dashboard["payload"]["from"] == "researcher"
        assert dashboard["payload"]["to"] == "writer"

    def test_cost_update_passes_through(self):
        event = create_event(COST_UPDATE, {
            "agent_id": "researcher", "cost": 0.003, "tokens_in": 1200
        })
        dashboard = to_dashboard_event(event)
        assert dashboard["type"] == "cost_update"
        assert dashboard["payload"]["cost"] == 0.003

    def test_run_started_maps_to_pipeline_progress(self):
        event = create_event(RUN_STARTED, {"run_id": "run_1", "name": "Test Run"})
        dashboard = to_dashboard_event(event)
        assert dashboard["type"] == "pipeline_progress"
        assert "Test Run" in dashboard["payload"]["message"]


class TestValidateEvent:
    def test_valid_event_returns_no_errors(self):
        event = create_event(AGENT_STARTED, {"agent_id": "test"})
        errors = validate_event(event)
        assert errors == []

    def test_missing_type_returns_error(self):
        errors = validate_event({"payload": {}})
        assert len(errors) == 1
        assert "type" in errors[0].lower()

    def test_unknown_type_returns_error(self):
        errors = validate_event({"type": "unknown.event"})
        assert len(errors) == 1
        assert "unknown" in errors[0].lower()

    def test_all_event_types_are_valid(self):
        for event_type in EVENT_TYPES:
            event = create_event(event_type, {})
            errors = validate_event(event)
            assert errors == [], f"Event type {event_type} should be valid"
