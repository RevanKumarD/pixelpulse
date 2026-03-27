"""Tests for the @observe() decorator in pixelpulse.decorators."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, call

import pytest

from pixelpulse.decorators import _current_agent, _format_input, _format_output, observe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pp():
    """Minimal PixelPulse-shaped mock."""
    pp = MagicMock()
    pp.agent_started = MagicMock()
    pp.agent_completed = MagicMock()
    pp.agent_error = MagicMock()
    pp.agent_thinking = MagicMock()
    pp.artifact_created = MagicMock()
    return pp


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class TestFormatHelpers:
    def test_format_input_positional_args(self):
        result = _format_input(("hello", "world"), {})
        assert "hello" in result
        assert "world" in result

    def test_format_input_keyword_args(self):
        result = _format_input((), {"query": "AI trends"})
        assert "query" in result
        assert "AI trends" in result

    def test_format_input_empty(self):
        assert _format_input((), {}) == "no input"

    def test_format_input_truncates_long_args(self):
        long_str = "x" * 200
        result = _format_input((long_str,), {})
        # Each arg is capped at 50 chars
        assert len(result) <= 60

    def test_format_output_none(self):
        assert _format_output(None) == ""

    def test_format_output_string(self):
        assert _format_output("hello") == "hello"

    def test_format_output_truncates(self):
        long_str = "y" * 500
        result = _format_output(long_str)
        assert len(result) == 300


# ---------------------------------------------------------------------------
# Sync function decoration
# ---------------------------------------------------------------------------


class TestSyncDecorator:
    def test_sync_function_returns_value(self, mock_pp):
        @observe(mock_pp, as_type="agent")
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_agent_started_emitted(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="my-agent")
        def work():
            return "done"

        work()
        mock_pp.agent_started.assert_called_once()
        assert mock_pp.agent_started.call_args[0][0] == "my-agent"

    def test_agent_completed_emitted(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="my-agent")
        def work():
            return "final output"

        work()
        mock_pp.agent_completed.assert_called_once()
        call_args = mock_pp.agent_completed.call_args
        assert call_args[0][0] == "my-agent"
        assert "final output" in call_args[1].get("output", "")

    def test_default_name_uses_function_name(self, mock_pp):
        @observe(mock_pp, as_type="agent")
        def my_researcher():
            return "result"

        my_researcher()
        assert mock_pp.agent_started.call_args[0][0] == "my_researcher"

    def test_custom_name_overrides_function_name(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="custom-name")
        def some_func():
            return "x"

        some_func()
        assert mock_pp.agent_started.call_args[0][0] == "custom-name"

    def test_agent_error_emitted_on_exception(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="failing-agent")
        def bad_func():
            raise ValueError("Something went wrong")

        with pytest.raises(ValueError, match="Something went wrong"):
            bad_func()

        mock_pp.agent_error.assert_called_once()
        call_args = mock_pp.agent_error.call_args
        assert call_args[0][0] == "failing-agent"
        assert "Something went wrong" in call_args[1].get("error", "")

    def test_exception_is_re_raised(self, mock_pp):
        @observe(mock_pp, as_type="agent")
        def raises():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            raises()

    def test_capture_input_false_does_not_include_args(self, mock_pp):
        @observe(mock_pp, as_type="agent", capture_input=False)
        def func(secret="password123"):
            return "ok"

        func(secret="password123")
        task_arg = mock_pp.agent_started.call_args[1].get("task", "")
        assert "password123" not in task_arg

    def test_capture_output_false_does_not_include_result(self, mock_pp):
        @observe(mock_pp, as_type="agent", capture_output=False)
        def func():
            return "secret result"

        func()
        output_arg = mock_pp.agent_completed.call_args[1].get("output", "")
        assert "secret result" not in output_arg


# ---------------------------------------------------------------------------
# Tool type
# ---------------------------------------------------------------------------


class TestToolType:
    def test_tool_emits_thinking_not_started(self, mock_pp):
        @observe(mock_pp, as_type="tool", name="web_search")
        def web_search(q):
            return "results"

        web_search("AI news")
        mock_pp.agent_started.assert_not_called()
        mock_pp.agent_thinking.assert_called_once()

    def test_tool_emits_artifact_not_completed(self, mock_pp):
        @observe(mock_pp, as_type="tool", name="web_search")
        def web_search(q):
            return "results"

        web_search("AI news")
        mock_pp.agent_completed.assert_not_called()
        mock_pp.artifact_created.assert_called_once()

    def test_tool_thinking_contains_tool_name(self, mock_pp):
        @observe(mock_pp, as_type="tool", name="calculator")
        def calculator(expr):
            return 42

        calculator("2+2")
        thought = mock_pp.agent_thinking.call_args[1].get("thought", "")
        assert "calculator" in thought

    def test_tool_artifact_contains_tool_name_and_output(self, mock_pp):
        @observe(mock_pp, as_type="tool", name="summariser")
        def summariser(text):
            return "Short summary"

        summariser("Long text here")
        content = mock_pp.artifact_created.call_args[1].get("content", "")
        assert "summariser" in content
        assert "Short summary" in content


# ---------------------------------------------------------------------------
# Async function decoration
# ---------------------------------------------------------------------------


class TestAsyncDecorator:
    def test_async_function_returns_value(self, mock_pp):
        @observe(mock_pp, as_type="agent")
        async def async_work():
            return "async result"

        result = asyncio.get_event_loop().run_until_complete(async_work())
        assert result == "async result"

    def test_async_agent_started_emitted(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="async-agent")
        async def async_work():
            return "done"

        asyncio.get_event_loop().run_until_complete(async_work())
        mock_pp.agent_started.assert_called_once()
        assert mock_pp.agent_started.call_args[0][0] == "async-agent"

    def test_async_agent_completed_emitted(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="async-agent")
        async def async_work():
            return "async output"

        asyncio.get_event_loop().run_until_complete(async_work())
        mock_pp.agent_completed.assert_called_once()
        output = mock_pp.agent_completed.call_args[1].get("output", "")
        assert "async output" in output

    def test_async_error_emitted(self, mock_pp):
        @observe(mock_pp, as_type="agent", name="async-fail")
        async def async_fail():
            raise ValueError("async error")

        with pytest.raises(ValueError, match="async error"):
            asyncio.get_event_loop().run_until_complete(async_fail())

        mock_pp.agent_error.assert_called_once()
        error = mock_pp.agent_error.call_args[1].get("error", "")
        assert "async error" in error


# ---------------------------------------------------------------------------
# Nested decorators / context propagation
# ---------------------------------------------------------------------------


class TestNestedDecorators:
    def test_parent_context_available_in_child(self, mock_pp):
        """When a tool is called inside an agent, the tool's thinking is
        attributed to the parent agent."""
        captured_parent: list[str | None] = []

        @observe(mock_pp, as_type="tool", name="inner-tool")
        def inner_tool():
            # At execution time the current_agent is set to inner-tool,
            # but the agent_thinking call should use the parent (outer-agent)
            captured_parent.append(_current_agent.get())
            return "tool result"

        @observe(mock_pp, as_type="agent", name="outer-agent")
        def outer_agent():
            return inner_tool()

        outer_agent()

        # inner_tool sets itself as current during its execution
        assert captured_parent[0] == "inner-tool"

        # The thinking event should be attributed to the outer-agent (parent)
        thinking_agent_id = mock_pp.agent_thinking.call_args[0][0]
        assert thinking_agent_id == "outer-agent"

    def test_context_restored_after_call(self, mock_pp):
        """After a decorated call the context var should be restored."""
        @observe(mock_pp, as_type="agent", name="solo-agent")
        def solo():
            return "done"

        assert _current_agent.get() is None
        solo()
        assert _current_agent.get() is None

    def test_context_restored_after_error(self, mock_pp):
        """Context var must be reset even when the function raises."""
        @observe(mock_pp, as_type="agent", name="crash-agent")
        def crash():
            raise RuntimeError("crash")

        with pytest.raises(RuntimeError):
            crash()

        assert _current_agent.get() is None
