"""Tests for the AutoGen adapter.

All tests use mocks so they work without autogen-agentchat installed.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from pixelpulse.adapters.autogen import AutoGenAdapter, _extract_content, _extract_source, _safe_str

# ---------------------------------------------------------------------------
# Helpers -- lightweight fakes that mimic AutoGen message shapes
# ---------------------------------------------------------------------------

class TextMessage:
    """Mimics autogen_agentchat.messages.TextMessage."""

    def __init__(self, content: str, source: str) -> None:
        self.content = content
        self.source = source


class StopMessage:
    """Mimics autogen_agentchat.messages.StopMessage."""

    def __init__(self, content: str, source: str) -> None:
        self.content = content
        self.source = source


class HandoffMessage:
    """Mimics autogen_agentchat.messages.HandoffMessage."""

    def __init__(self, content: str, source: str) -> None:
        self.content = content
        self.source = source


class FakeFunctionCall:
    """Mimics autogen_core.FunctionCall."""

    def __init__(self, name: str, arguments: str, call_id: str = "call_1") -> None:
        self.name = name
        self.arguments = arguments
        self.id = call_id


class ToolCallRequestEvent:
    """Mimics autogen_agentchat.messages.ToolCallRequestEvent."""

    def __init__(self, source: str, content: list) -> None:
        self.source = source
        self.content = content


class FakeFunctionExecutionResult:
    """Mimics autogen_core.models.FunctionExecutionResult."""

    def __init__(self, call_id: str, content: str) -> None:
        self.call_id = call_id
        self.content = content


class ToolCallExecutionEvent:
    """Mimics autogen_agentchat.messages.ToolCallExecutionEvent."""

    def __init__(self, source: str, content: list) -> None:
        self.source = source
        self.content = content


class TaskResult:
    """Mimics autogen_agentchat.base.TaskResult."""

    def __init__(self, messages: list | None = None, stop_reason: str = "") -> None:
        self.messages = messages or []
        self.stop_reason = stop_reason


class FakeAgent:
    """Mimics a minimal AutoGen AssistantAgent."""

    def __init__(self, name: str) -> None:
        self.name = name


class FakeTeam:
    """Mimics a RoundRobinGroupChat with run / run_stream."""

    def __init__(self, agents: list[FakeAgent] | None = None) -> None:
        self._participants = agents or []

    async def run(self, task: str = "") -> TaskResult:
        return TaskResult(
            messages=[TextMessage("Done", "coder")],
            stop_reason="MaxMessages",
        )

    async def run_stream(self, task: str = ""):
        messages = [
            TextMessage("Let me write the code", "coder"),
            TextMessage("Looks good, APPROVE", "reviewer"),
            StopMessage("TERMINATE", "coder"),
        ]
        for msg in messages:
            yield msg
        yield TaskResult(messages=messages, stop_reason="TextMention")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_pp() -> MagicMock:
    """Return a mock PixelPulse instance that records all emitted events."""
    pp = MagicMock()
    pp.agent_started = MagicMock()
    pp.agent_completed = MagicMock()
    pp.agent_error = MagicMock()
    pp.agent_thinking = MagicMock()
    pp.agent_message = MagicMock()
    pp.artifact_created = MagicMock()
    pp.cost_update = MagicMock()
    pp.run_started = MagicMock()
    pp.run_completed = MagicMock()
    pp.stage_entered = MagicMock()
    pp.stage_exited = MagicMock()
    return pp


@pytest.fixture()
def team() -> FakeTeam:
    return FakeTeam(agents=[FakeAgent("coder"), FakeAgent("reviewer")])


@pytest.fixture()
def adapter(mock_pp: MagicMock) -> AutoGenAdapter:
    return AutoGenAdapter(mock_pp)


# ---------------------------------------------------------------------------
# Tests: creation and instrumentation
# ---------------------------------------------------------------------------

class TestAdapterCreation:
    def test_init_stores_pp_reference(self, mock_pp: MagicMock) -> None:
        adapter = AutoGenAdapter(mock_pp)
        assert adapter._pp is mock_pp

    def test_instrument_wraps_run_and_run_stream(
        self, adapter: AutoGenAdapter, team: FakeTeam
    ) -> None:
        adapter.instrument(team)

        # Original methods are stored (callable references)
        assert adapter._original_run is not None
        assert adapter._original_run_stream is not None
        # The wrapped methods should be our adapter's methods
        assert team.run == adapter._wrapped_run
        assert team.run_stream == adapter._wrapped_run_stream

    def test_instrument_discovers_agents(
        self, adapter: AutoGenAdapter, team: FakeTeam
    ) -> None:
        adapter.instrument(team)
        assert len(adapter._agents) == 2
        assert adapter._agents[0].name == "coder"
        assert adapter._agents[1].name == "reviewer"


# ---------------------------------------------------------------------------
# Tests: message translation
# ---------------------------------------------------------------------------

class TestMessageTranslation:
    def test_text_message_emits_thinking(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        adapter.instrument(FakeTeam())
        msg = TextMessage("Hello world", "coder")

        adapter._translate_message(msg, "run-1")

        # First time seeing "coder" => agent_started
        mock_pp.agent_started.assert_called_once_with("coder", task="Hello world")
        # TextMessage content is emitted as thinking
        mock_pp.agent_thinking.assert_called()
        thought_text = mock_pp.agent_thinking.call_args[1]["thought"]
        assert "Hello world" in thought_text

    def test_stop_message_emits_completed(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        adapter.instrument(FakeTeam())
        # First, make reviewer "active" by sending a text message
        adapter._translate_message(TextMessage("Reviewing...", "reviewer"), "run-1")
        mock_pp.reset_mock()

        # Now send a StopMessage from reviewer
        msg = StopMessage("TERMINATE", "reviewer")
        adapter._translate_message(msg, "run-1")

        mock_pp.agent_completed.assert_called_once_with("reviewer", output="TERMINATE")

    def test_tool_call_request_emits_thinking(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        adapter.instrument(FakeTeam())
        func = FakeFunctionCall("search_web", '{"query": "test"}')
        msg = ToolCallRequestEvent("coder", [func])

        adapter._translate_message(msg, "run-1")

        # Should emit agent_thinking with tool info
        thinking_calls = mock_pp.agent_thinking.call_args_list
        assert len(thinking_calls) >= 1
        thought_text = thinking_calls[-1][1]["thought"]
        assert "search_web" in thought_text

    def test_tool_execution_emits_artifact(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        adapter.instrument(FakeTeam())
        # Use an agent name (not "tools") so it maps to a real agent
        result = FakeFunctionExecutionResult("call_1", "Search returned 5 items")
        msg = ToolCallExecutionEvent("coder", [result])

        adapter._translate_message(msg, "run-1")

        mock_pp.artifact_created.assert_called_once()
        args = mock_pp.artifact_created.call_args
        assert args[1]["artifact_type"] == "tool_result"
        assert "5 items" in args[1]["content"]

    def test_agent_to_agent_message_on_source_change(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        """When the message source changes, an agent_message event should fire."""
        adapter.instrument(FakeTeam())

        # First message from coder
        adapter._translate_message(TextMessage("Code done", "coder"), "run-1")
        # Second message from reviewer (source change => agent_message)
        adapter._translate_message(TextMessage("Looks good", "reviewer"), "run-1")

        mock_pp.agent_message.assert_called_once()
        call_kwargs = mock_pp.agent_message.call_args
        assert call_kwargs[0][0] == "coder"  # from
        assert call_kwargs[0][1] == "reviewer"  # to


# ---------------------------------------------------------------------------
# Tests: run lifecycle
# ---------------------------------------------------------------------------

class TestRunLifecycle:
    def test_run_stream_emits_start_and_complete(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock, team: FakeTeam
    ) -> None:
        adapter.instrument(team)

        async def _run():
            messages = []
            async for msg in team.run_stream(task="Write Fibonacci"):
                messages.append(msg)
            return messages

        asyncio.run(_run())

        mock_pp.run_started.assert_called_once()
        # run_started(run_id, name=...)
        call_args = mock_pp.run_started.call_args
        # name can be positional or keyword
        name_arg = call_args[1].get("name") or (call_args[0][1] if len(call_args[0]) > 1 else "")
        assert "Fibonacci" in name_arg
        mock_pp.run_completed.assert_called_once()
        completed_args = mock_pp.run_completed.call_args
        # Check status is "completed"
        status = completed_args[1].get("status") or (completed_args[0][1] if len(completed_args[0]) > 1 else "")
        assert status == "completed"

    def test_run_emits_start_and_complete(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock, team: FakeTeam
    ) -> None:
        adapter.instrument(team)

        result = asyncio.run(team.run(task="Build a calculator"))

        mock_pp.run_started.assert_called_once()
        mock_pp.run_completed.assert_called_once()
        # Verify the run_id matches between start and complete
        start_run_id = mock_pp.run_started.call_args[0][0]
        complete_run_id = mock_pp.run_completed.call_args[0][0]
        assert start_run_id == complete_run_id

    def test_run_error_emits_error_status(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        """When the team raises, run_completed should fire with status='error'."""

        class FailingTeam:
            _participants = [FakeAgent("coder")]

            async def run(self, task=""):
                raise RuntimeError("LLM timeout")

            async def run_stream(self, task=""):
                yield TextMessage("starting", "coder")
                raise RuntimeError("LLM timeout")

        failing = FailingTeam()
        adapter.instrument(failing)

        with pytest.raises(RuntimeError, match="LLM timeout"):
            asyncio.run(failing.run(task="fail"))

        mock_pp.run_completed.assert_called_once()
        # status can be positional or keyword
        call_args = mock_pp.run_completed.call_args
        status = call_args[1].get("status") or (call_args[0][1] if len(call_args[0]) > 1 else "")
        assert status == "error"

    def test_run_stream_error_marks_active_agents(
        self, adapter: AutoGenAdapter, mock_pp: MagicMock
    ) -> None:
        """Active agents should get error events when run_stream fails."""

        class FailStreamTeam:
            _participants = [FakeAgent("coder")]

            async def run(self, task=""):
                pass

            async def run_stream(self, task=""):
                yield TextMessage("working on it", "coder")
                raise RuntimeError("Network error")

        failing = FailStreamTeam()
        adapter.instrument(failing)

        with pytest.raises(RuntimeError, match="Network error"):
            async def _drain():
                async for _ in failing.run_stream(task="boom"):
                    pass
            asyncio.run(_drain())

        # coder was active when the error hit
        mock_pp.agent_error.assert_called()
        error_agent = mock_pp.agent_error.call_args[0][0]
        assert error_agent == "coder"


# ---------------------------------------------------------------------------
# Tests: detach / cleanup
# ---------------------------------------------------------------------------

class TestDetach:
    def test_detach_restores_original_methods(
        self, adapter: AutoGenAdapter, team: FakeTeam
    ) -> None:
        adapter.instrument(team)
        # After instrument, methods are our wrappers
        assert team.run == adapter._wrapped_run

        adapter.detach()
        # After detach, the wrapped methods should no longer be our wrappers
        # (they should be the original bound methods restored from _original_run)
        assert team.run != adapter._wrapped_run
        # And the adapter should have cleared its references
        assert adapter._original_run is None
        assert adapter._original_run_stream is None

    def test_detach_clears_state(
        self, adapter: AutoGenAdapter, team: FakeTeam
    ) -> None:
        adapter.instrument(team)
        adapter._active_agents.add("coder")

        adapter.detach()

        assert adapter._team is None
        assert adapter._agents == []
        assert len(adapter._active_agents) == 0

    def test_detach_is_idempotent(self, adapter: AutoGenAdapter) -> None:
        """Calling detach without instrument should not raise."""
        adapter.detach()  # no-op
        adapter.detach()  # still no-op


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_extract_source_from_message(self) -> None:
        msg = TextMessage("hi", "My Agent")
        assert _extract_source(msg) == "my-agent"

    def test_extract_source_fallback(self) -> None:
        assert _extract_source(object()) == "unknown-agent"

    def test_extract_content_from_text(self) -> None:
        msg = TextMessage("Hello world", "user")
        assert _extract_content(msg) == "Hello world"

    def test_extract_content_from_tool_calls(self) -> None:
        func = FakeFunctionCall("search", '{"q": "test"}')
        msg = ToolCallRequestEvent("agent", [func])
        content = _extract_content(msg)
        assert "search" in content
        assert "test" in content

    def test_safe_str_truncates(self) -> None:
        long = "x" * 500
        assert len(_safe_str(long, 100)) == 100

    def test_safe_str_handles_none(self) -> None:
        assert _safe_str(None) == ""

    def test_tag_for_message_types(self) -> None:
        adapter = AutoGenAdapter(MagicMock())
        assert adapter._tag_for_message("TextMessage") == "data"
        assert adapter._tag_for_message("StopMessage") == "control"
        assert adapter._tag_for_message("HandoffMessage") == "handoff"
        assert adapter._tag_for_message("ToolCallRequestEvent") == "tool"
        assert adapter._tag_for_message("UnknownType") == "data"


# ---------------------------------------------------------------------------
# Tests: single-agent wrapping (on_messages)
# ---------------------------------------------------------------------------

class TestSingleAgentWrapping:
    def test_wraps_on_messages(self, mock_pp: MagicMock) -> None:
        """When instrumenting a single agent (no run_stream), on_messages is wrapped."""

        class SingleAgent:
            name = "solo"

            async def on_messages(self, messages, cancellation_token=None):
                result = MagicMock()
                result.chat_message = "I am done"
                return result

        agent = SingleAgent()
        adapter = AutoGenAdapter(mock_pp)
        adapter.instrument(agent)

        result = asyncio.run(agent.on_messages([TextMessage("Do stuff", "user")]))

        mock_pp.agent_started.assert_called_once_with("solo", task="Do stuff")
        mock_pp.agent_completed.assert_called_once()
        assert "done" in mock_pp.agent_completed.call_args[1]["output"].lower()

    def test_on_messages_error_emits_agent_error(self, mock_pp: MagicMock) -> None:
        class FailingAgent:
            name = "broken"

            async def on_messages(self, messages, cancellation_token=None):
                raise ValueError("Bad input")

        agent = FailingAgent()
        adapter = AutoGenAdapter(mock_pp)
        adapter.instrument(agent)

        with pytest.raises(ValueError, match="Bad input"):
            asyncio.run(agent.on_messages([TextMessage("Go", "user")]))

        mock_pp.agent_error.assert_called_once()
        assert "Bad input" in mock_pp.agent_error.call_args[1]["error"]
