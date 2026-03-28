"""Tests for the Claude Code adapter."""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from pixelpulse.adapters.claude_code import (
    ClaudeCodeAdapter,
    _estimate_cost,
    _sanitize_tool_name,
)


# ---- Utility Tests ----


class TestSanitizeToolName:
    def test_normal_tool(self):
        assert _sanitize_tool_name("Read") == "read"

    def test_mcp_tool(self):
        assert _sanitize_tool_name("mcp__memory__search") == "mcp:memory:search"

    def test_empty(self):
        assert _sanitize_tool_name("") == "unknown-tool"

    def test_none(self):
        assert _sanitize_tool_name(None) == "unknown-tool"

    def test_spaces(self):
        assert _sanitize_tool_name("Web Search") == "web-search"


class TestEstimateCost:
    def test_opus_pricing(self):
        # Opus 4.6: $5/MTok in, $25/MTok out
        # 1000 in → $0.005, 500 out → $0.0125
        cost = _estimate_cost("claude-opus-4-20250514", 1000, 500)
        assert cost == pytest.approx(0.005 + 0.0125, rel=1e-2)

    def test_sonnet_pricing(self):
        # Sonnet 4.6: $3/MTok in, $15/MTok out
        # 1000 in → $0.003, 500 out → $0.0075
        cost = _estimate_cost("claude-sonnet-4-20250514", 1000, 500)
        assert cost == pytest.approx(0.003 + 0.0075, rel=1e-2)

    def test_unknown_model_fallback(self):
        cost = _estimate_cost("unknown-model", 1000, 500)
        assert cost > 0

    def test_zero_tokens(self):
        assert _estimate_cost("claude-sonnet-4", 0, 0) == 0.0


# ---- Adapter Tests ----


def _make_adapter():
    pp = MagicMock()
    pp._agents = {"claude": {"team": "coding", "role": "Assistant"}}
    adapter = ClaudeCodeAdapter(pp)
    return adapter, pp


class TestAdapterCreation:
    def test_init(self):
        adapter, pp = _make_adapter()
        assert adapter._active is False
        assert adapter._session_id is None

    def test_instrument(self):
        adapter, pp = _make_adapter()
        adapter.instrument()
        assert adapter._active is True
        assert adapter._agent_name == "claude"


class TestSessionLifecycle:
    def test_session_start(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "test-session-1",
        })
        pp.run_started.assert_called_once()
        pp.agent_started.assert_called_once()
        assert adapter._session_id == "test-session-1"

    def test_session_end(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "test-session-1",
        })
        adapter.on_hook_event({
            "hook_event_name": "SessionEnd",
            "session_id": "test-session-1",
        })
        pp.agent_completed.assert_called_once()
        pp.run_completed.assert_called_once()

    def test_new_session_ends_previous(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "session-1",
        })
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "session-2",
        })
        # First session's run_completed + second session's run_started
        assert pp.run_completed.call_count == 1
        assert pp.run_started.call_count == 2


class TestToolEvents:
    def test_pre_tool_use_bash(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        })
        pp.agent_thinking.assert_called()
        thought = pp.agent_thinking.call_args[1].get("thought", "") or pp.agent_thinking.call_args[0][1] if len(pp.agent_thinking.call_args[0]) > 1 else ""
        # Check via kwargs
        calls = pp.agent_thinking.call_args_list
        assert any("git status" in str(c) for c in calls)

    def test_post_tool_use_creates_artifact(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/test/file.py"},
        })
        adapter.on_hook_event({
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_response": "file contents here",
        })
        pp.artifact_created.assert_called_once()

    def test_pre_tool_use_read(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/path/to/file.py"},
        })
        calls = pp.agent_thinking.call_args_list
        assert any("/path/to/file.py" in str(c) for c in calls)

    def test_pre_tool_use_grep(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Grep",
            "tool_input": {"pattern": "def main"},
        })
        calls = pp.agent_thinking.call_args_list
        assert any("def main" in str(c) for c in calls)


class TestSubagentEvents:
    def test_subagent_start(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "SubagentStart",
            "session_id": "s1",
            "subagent_type": "Explore",
            "description": "Search for config files",
        })
        calls = pp.agent_thinking.call_args_list
        assert any("subagent" in str(c).lower() for c in calls)

    def test_subagent_stop_with_transcript(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "SubagentStop",
            "session_id": "s1",
            "agent_transcript_path": "/tmp/transcript.jsonl",
        })
        pp.artifact_created.assert_called_once()


class TestCostTracking:
    def test_stop_with_usage(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "Stop",
            "session_id": "s1",
            "last_assistant_message": {
                "usage": {"input_tokens": 1000, "output_tokens": 500},
                "model": "claude-sonnet-4-20250514",
            },
        })
        pp.cost_update.assert_called_once()
        assert adapter._accumulated_cost > 0

    def test_stop_without_usage(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.on_hook_event({
            "hook_event_name": "Stop",
            "session_id": "s1",
            "last_assistant_message": "just text",
        })
        pp.cost_update.assert_not_called()


class TestHooksConfig:
    def test_generate_default_port(self):
        adapter, _ = _make_adapter()
        config = adapter.generate_hooks_config()
        assert "hooks" in config
        hooks = config["hooks"]
        assert "PreToolUse" in hooks
        assert "PostToolUse" in hooks
        assert "SessionStart" in hooks
        assert "Stop" in hooks
        assert hooks["PreToolUse"][0]["url"] == "http://localhost:8765/hooks/claude-code"

    def test_generate_custom_port(self):
        adapter, _ = _make_adapter()
        config = adapter.generate_hooks_config(port=9999)
        assert "9999" in config["hooks"]["PreToolUse"][0]["url"]


class TestDetach:
    def test_detach_ends_session(self):
        adapter, pp = _make_adapter()
        adapter.on_hook_event({
            "hook_event_name": "SessionStart",
            "session_id": "s1",
        })
        adapter.detach()
        pp.run_completed.assert_called_once()
        assert adapter._active is False

    def test_detach_without_session(self):
        adapter, pp = _make_adapter()
        adapter.detach()
        pp.run_completed.assert_not_called()


class TestTranscriptReplay:
    def test_replay_nonexistent_file(self):
        adapter, pp = _make_adapter()
        adapter.replay_transcript("/nonexistent/path.jsonl")
        pp.run_started.assert_not_called()

    def test_replay_simple_transcript(self, tmp_path):
        import json

        transcript = tmp_path / "test.jsonl"
        lines = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check that..."},
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/test.py"}},
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "model": "claude-sonnet-4",
            },
            {
                "role": "tool",
                "tool_use_id": "tu_123",
                "content": "def main(): pass",
            },
        ]
        transcript.write_text("\n".join(json.dumps(l) for l in lines))

        adapter, pp = _make_adapter()
        adapter.replay_transcript(str(transcript))

        pp.run_started.assert_called_once()
        pp.agent_started.assert_called_once()
        # Thinking from text block + thinking from tool_use
        assert pp.agent_thinking.call_count >= 2
        # Artifact from tool result
        pp.artifact_created.assert_called_once()
        # Cost update from usage
        pp.cost_update.assert_called_once()
        # Completion
        assert pp.agent_completed.call_count >= 1
        pp.run_completed.assert_called_once()
