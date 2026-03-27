"""Unit tests for storage models."""
from __future__ import annotations

import json

import pytest

from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus


class TestRunStatus:
    def test_values(self):
        assert RunStatus.ACTIVE == "active"
        assert RunStatus.COMPLETED == "completed"
        assert RunStatus.FAILED == "failed"
        assert RunStatus.CANCELED == "canceled"

    def test_is_string(self):
        assert isinstance(RunStatus.ACTIVE, str)


class TestRunRecord:
    def test_defaults(self):
        run = RunRecord(id="run_abc123")
        assert run.id == "run_abc123"
        assert run.name == ""
        assert run.status == RunStatus.ACTIVE
        assert run.total_cost == 0.0
        assert run.event_count == 0
        assert run.metadata == {}

    def test_immutable(self):
        run = RunRecord(id="run_abc123", name="Test")
        with pytest.raises(AttributeError):
            run.name = "Changed"

    def test_to_dict(self):
        run = RunRecord(
            id="run_abc",
            name="Test Run",
            status=RunStatus.COMPLETED,
            started_at="2026-03-27T10:00:00Z",
            completed_at="2026-03-27T10:05:00Z",
            total_cost=0.05,
            total_tokens_in=1000,
            total_tokens_out=500,
            agent_count=3,
            event_count=42,
            metadata={"key": "value"},
        )
        d = run.to_dict()
        assert d["id"] == "run_abc"
        assert d["name"] == "Test Run"
        assert d["status"] == "completed"
        assert d["total_cost"] == 0.05
        assert d["metadata"] == {"key": "value"}

    def test_from_row(self):
        row = (
            "run_abc",
            "Test",
            "completed",
            "2026-03-27T10:00:00Z",
            "2026-03-27T10:05:00Z",
            0.05,
            1000,
            500,
            3,
            42,
            '{"key": "value"}',
        )
        run = RunRecord.from_row(row)
        assert run.id == "run_abc"
        assert run.name == "Test"
        assert run.status == "completed"
        assert run.total_cost == 0.05
        assert run.metadata == {"key": "value"}

    def test_from_row_null_fields(self):
        row = ("run_abc", "", "active", "2026-03-27T10:00:00Z", None, 0, 0, 0, 0, 0, None)
        run = RunRecord.from_row(row)
        assert run.completed_at == ""
        assert run.metadata == {}

    def test_roundtrip(self):
        original = RunRecord(
            id="run_round",
            name="Roundtrip Test",
            status=RunStatus.FAILED,
            started_at="2026-03-27T10:00:00Z",
            total_cost=1.23,
            metadata={"nested": {"deep": True}},
        )
        d = original.to_dict()
        # Simulate from_row conversion
        row = (
            d["id"], d["name"], d["status"], d["started_at"],
            d["completed_at"] or None, d["total_cost"],
            d["total_tokens_in"], d["total_tokens_out"],
            d["agent_count"], d["event_count"],
            json.dumps(d["metadata"]),
        )
        restored = RunRecord.from_row(row)
        assert restored.id == original.id
        assert restored.status == original.status
        assert restored.metadata == original.metadata


class TestEventRecord:
    def test_defaults(self):
        event = EventRecord(id="evt_abc", run_id="run_1", type="agent_status", timestamp="t1")
        assert event.source_framework == ""
        assert event.payload == {}
        assert event.agent_id == ""

    def test_immutable(self):
        event = EventRecord(id="evt_abc", run_id="run_1", type="agent_status", timestamp="t1")
        with pytest.raises(AttributeError):
            event.type = "changed"

    def test_to_dict(self):
        event = EventRecord(
            id="evt_abc",
            run_id="run_1",
            type="cost_update",
            timestamp="2026-03-27T10:00:00Z",
            source_framework="crewai",
            payload={"cost": 0.01, "agent_id": "researcher"},
            agent_id="researcher",
        )
        d = event.to_dict()
        assert d["id"] == "evt_abc"
        assert d["payload"]["cost"] == 0.01

    def test_from_row(self):
        row = (
            "evt_abc",
            "run_1",
            "agent_status",
            "2026-03-27T10:00:00Z",
            "crewai",
            '{"status": "active"}',
            "researcher",
        )
        event = EventRecord.from_row(row)
        assert event.id == "evt_abc"
        assert event.payload == {"status": "active"}
        assert event.agent_id == "researcher"

    def test_from_row_null_fields(self):
        row = ("evt_abc", "run_1", "agent_status", "t1", None, None, None)
        event = EventRecord.from_row(row)
        assert event.source_framework == ""
        assert event.payload == {}
        assert event.agent_id == ""
