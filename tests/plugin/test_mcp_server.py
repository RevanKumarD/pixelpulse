"""Tests for the PixelPulse MCP server tools.

These test the aggregation logic — each tool's _impl function takes
raw event data and returns the expected shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "claude-code" / "mcp-server"
sys.path.insert(0, str(SCRIPTS_DIR))


# ---- Test data ----

SAMPLE_EVENTS = [
    {
        "type": "agent_status",
        "payload": {"agent": "claude", "status": "active", "task": "Coding"},
        "timestamp": "2026-03-27T10:00:00Z",
    },
    {
        "type": "agent_status",
        "payload": {"agent": "claude", "status": "thinking", "thought": "Using read: /src/main.py"},
        "timestamp": "2026-03-27T10:00:01Z",
    },
    {
        "type": "cost_update",
        "payload": {
            "agent": "claude",
            "cost": 0.015,
            "tokens_in": 1000,
            "tokens_out": 500,
            "model": "claude-sonnet-4",
        },
        "timestamp": "2026-03-27T10:00:02Z",
    },
    {
        "type": "cost_update",
        "payload": {
            "agent": "claude",
            "cost": 0.045,
            "tokens_in": 2000,
            "tokens_out": 1000,
            "model": "claude-opus-4",
        },
        "timestamp": "2026-03-27T10:00:05Z",
    },
    {
        "type": "artifact_event",
        "payload": {
            "agent": "claude",
            "artifact_type": "file_read_result",
            "content": "Read: file contents...",
        },
        "timestamp": "2026-03-27T10:00:03Z",
    },
    {
        "type": "agent_status",
        "payload": {"agent": "claude", "status": "thinking", "thought": "Using bash: npm test"},
        "timestamp": "2026-03-27T10:00:04Z",
    },
    {
        "type": "agent_status",
        "payload": {"agent": "researcher", "status": "active", "task": "Find files"},
        "timestamp": "2026-03-27T10:00:06Z",
    },
    {
        "type": "agent_status",
        "payload": {"agent": "researcher", "status": "idle", "output": "Done"},
        "timestamp": "2026-03-27T10:00:08Z",
    },
]


class TestSessionStats:
    def test_aggregates_costs_and_tokens(self):
        from server import aggregate_session_stats

        stats = aggregate_session_stats(SAMPLE_EVENTS)
        assert stats["cost"] == pytest.approx(0.06, rel=1e-2)
        assert stats["tokens_in"] == 3000
        assert stats["tokens_out"] == 1500

    def test_counts_tool_calls(self):
        from server import aggregate_session_stats

        stats = aggregate_session_stats(SAMPLE_EVENTS)
        assert stats["tool_calls"] == 2

    def test_counts_subagents(self):
        from server import aggregate_session_stats

        stats = aggregate_session_stats(SAMPLE_EVENTS)
        assert stats["subagents_spawned"] >= 1

    def test_empty_events(self):
        from server import aggregate_session_stats

        stats = aggregate_session_stats([])
        assert stats["cost"] == 0.0
        assert stats["tool_calls"] == 0


class TestCostBreakdown:
    def test_groups_by_model(self):
        from server import aggregate_cost_breakdown

        breakdown = aggregate_cost_breakdown(SAMPLE_EVENTS)
        models = {entry["model"] for entry in breakdown}
        assert "claude-sonnet-4" in models
        assert "claude-opus-4" in models

    def test_sums_per_model(self):
        from server import aggregate_cost_breakdown

        breakdown = aggregate_cost_breakdown(SAMPLE_EVENTS)
        sonnet = next(e for e in breakdown if e["model"] == "claude-sonnet-4")
        assert sonnet["tokens_in"] == 1000
        assert sonnet["cost"] == pytest.approx(0.015, rel=1e-2)
        assert sonnet["calls"] == 1

    def test_empty_events(self):
        from server import aggregate_cost_breakdown

        assert aggregate_cost_breakdown([]) == []


class TestToolSummary:
    def test_extracts_tool_names(self):
        from server import aggregate_tool_summary

        summary = aggregate_tool_summary(SAMPLE_EVENTS)
        tool_names = {entry["tool"] for entry in summary}
        assert "read" in tool_names
        assert "bash" in tool_names

    def test_counts_per_tool(self):
        from server import aggregate_tool_summary

        summary = aggregate_tool_summary(SAMPLE_EVENTS)
        read_entry = next(e for e in summary if e["tool"] == "read")
        assert read_entry["count"] == 1

    def test_empty_events(self):
        from server import aggregate_tool_summary

        assert aggregate_tool_summary([]) == []


class TestSubagentTree:
    def test_builds_tree_from_events(self):
        from server import build_subagent_tree

        tree = build_subagent_tree(SAMPLE_EVENTS)
        assert tree["id"] == "claude"
        assert tree["status"] in ("active", "idle", "thinking")

    def test_subagents_as_children(self):
        from server import build_subagent_tree

        tree = build_subagent_tree(SAMPLE_EVENTS)
        child_ids = [c["id"] for c in tree.get("children", [])]
        assert "researcher" in child_ids

    def test_empty_events(self):
        from server import build_subagent_tree

        tree = build_subagent_tree([])
        assert tree["id"] == "unknown"
        assert tree["children"] == []


class TestRecentEvents:
    def test_returns_last_n_events(self):
        from server import get_recent_events

        events = get_recent_events(SAMPLE_EVENTS, n=3)
        assert len(events) == 3

    def test_default_limit(self):
        from server import get_recent_events

        events = get_recent_events(SAMPLE_EVENTS)
        assert len(events) == len(SAMPLE_EVENTS)

    def test_empty_events(self):
        from server import get_recent_events

        assert get_recent_events([]) == []
