"""Tests for the Claude Code hook handler script."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the scripts directory to path so we can import the handler module
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "claude-code" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from tests.plugin.conftest import make_hook_payload


class TestParseHookEvent:
    """Test that the handler correctly parses all 7 hook event types from stdin."""

    def test_parse_session_start(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload("SessionStart")
        result = parse_stdin(payload)
        assert result["hook_event_name"] == "SessionStart"
        assert result["session_id"] == "test-session-001"

    def test_parse_pre_tool_use(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload(
            "PreToolUse", tool_name="Read", tool_input={"file_path": "/src/main.py"}
        )
        result = parse_stdin(payload)
        assert result["hook_event_name"] == "PreToolUse"
        assert result["tool_name"] == "Read"

    def test_parse_post_tool_use(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload(
            "PostToolUse", tool_name="Read", tool_response="file contents"
        )
        result = parse_stdin(payload)
        assert result["tool_name"] == "Read"
        assert result["tool_response"] == "file contents"

    def test_parse_subagent_start(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload(
            "SubagentStart", subagent_type="Explore", description="Find files"
        )
        result = parse_stdin(payload)
        assert result["subagent_type"] == "Explore"

    def test_parse_subagent_stop(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload(
            "SubagentStop", agent_transcript_path="/tmp/transcript.jsonl"
        )
        result = parse_stdin(payload)
        assert result["agent_transcript_path"] == "/tmp/transcript.jsonl"

    def test_parse_stop(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload(
            "Stop",
            last_assistant_message={
                "usage": {"input_tokens": 1000, "output_tokens": 500},
                "model": "claude-sonnet-4",
            },
        )
        result = parse_stdin(payload)
        assert result["last_assistant_message"]["usage"]["input_tokens"] == 1000

    def test_parse_session_end(self):
        from hook_handler import parse_stdin

        payload = make_hook_payload("SessionEnd")
        result = parse_stdin(payload)
        assert result["hook_event_name"] == "SessionEnd"

    def test_parse_invalid_json_returns_none(self):
        from hook_handler import parse_stdin

        result = parse_stdin("not valid json {{{")
        assert result is None

    def test_parse_empty_string_returns_none(self):
        from hook_handler import parse_stdin

        result = parse_stdin("")
        assert result is None


class TestBuildResponse:
    def test_always_returns_continue_true(self):
        from hook_handler import build_response

        result = build_response()
        assert result == {"continue": True}


class TestShouldEnsureServer:
    def test_session_start_triggers_ensure(self):
        from hook_handler import should_ensure_server

        assert should_ensure_server("SessionStart") is True

    def test_pre_tool_use_does_not_trigger(self):
        from hook_handler import should_ensure_server

        assert should_ensure_server("PreToolUse") is False

    def test_unknown_event_does_not_trigger(self):
        from hook_handler import should_ensure_server

        assert should_ensure_server("SomeOtherEvent") is False


class TestGetServerUrl:
    def test_default_port(self):
        from hook_handler import get_server_url

        url = get_server_url(port=8765)
        assert url == "http://localhost:8765/hooks/claude-code"

    def test_custom_port(self):
        from hook_handler import get_server_url

        url = get_server_url(port=9000)
        assert url == "http://localhost:9000/hooks/claude-code"
