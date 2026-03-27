"""Tests for the CrewAI adapter.

Uses mocks for all crewai imports so tests work without installing the SDK.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call
import pytest

from pixelpulse.adapters.crewai import (
    CrewAIAdapter,
    _estimate_cost,
    _extract_agent_role,
    _extract_token_usage,
    _sanitize_name,
)


@pytest.fixture
def mock_pp():
    """Create a mock PixelPulse instance."""
    pp = MagicMock()
    pp.agent_started = MagicMock()
    pp.agent_completed = MagicMock()
    pp.agent_error = MagicMock()
    pp.agent_thinking = MagicMock()
    pp.agent_message = MagicMock()
    pp.cost_update = MagicMock()
    pp.run_started = MagicMock()
    pp.run_completed = MagicMock()
    pp.artifact_created = MagicMock()
    pp.stage_entered = MagicMock()
    pp.stage_exited = MagicMock()
    return pp


def _make_crew(agents=None, tasks=None, name="Test Crew"):
    """Create a mock CrewAI Crew object."""
    crew = MagicMock()
    crew.name = name
    crew.agents = agents or []
    crew.tasks = tasks or []
    crew.step_callback = None
    crew.task_callback = None
    crew.usage_metrics = None

    # kickoff returns a mock result
    def mock_kickoff(*args, **kwargs):
        return MagicMock(raw="Test result output")

    crew.kickoff = mock_kickoff
    return crew


def _make_step_output(agent_role="Researcher", thought=None, tool=None,
                      tool_input=None, result=None, text=None):
    """Create a mock CrewAI step output."""
    step = MagicMock()
    agent = MagicMock()
    agent.role = agent_role
    step.agent = agent
    step.thought = thought
    step.tool = tool
    step.tool_input = tool_input
    step.result = result
    step.text = text
    step.action = None
    step.output = None
    return step


def _make_task_output(agent_role="Writer", raw="Task completed successfully",
                      token_usage=None):
    """Create a mock CrewAI task output."""
    output = MagicMock()
    agent = MagicMock()
    agent.role = agent_role
    output.agent = agent
    output.raw = raw
    output.description = None
    output.token_usage = token_usage
    output.usage = None
    return output


# -- Utility functions --

class TestUtilities:
    def test_sanitize_name_basic(self):
        assert _sanitize_name("Senior Researcher") == "senior-researcher"
        assert _sanitize_name("content_writer") == "content-writer"
        assert _sanitize_name(None) == "agent"
        assert _sanitize_name("") == "agent"

    def test_extract_agent_role(self):
        step = _make_step_output(agent_role="Quality Reviewer")
        assert _extract_agent_role(step) == "quality-reviewer"

    def test_extract_agent_role_fallback_to_name(self):
        step = MagicMock()
        agent = MagicMock()
        agent.role = None
        agent.name = "my-agent"
        step.agent = agent
        assert _extract_agent_role(step) == "my-agent"

    def test_extract_agent_role_no_agent(self):
        step = MagicMock()
        step.agent = None
        assert _extract_agent_role(step) == "unknown-agent"

    def test_extract_token_usage_dict(self):
        output = MagicMock()
        output.token_usage = {"prompt_tokens": 500, "completion_tokens": 200}
        output.usage = None
        result = _extract_token_usage(output)
        assert result["input_tokens"] == 500
        assert result["output_tokens"] == 200

    def test_extract_token_usage_alternative_keys(self):
        output = MagicMock()
        output.token_usage = {"input_tokens": 300, "output_tokens": 150}
        output.usage = None
        result = _extract_token_usage(output)
        assert result["input_tokens"] == 300
        assert result["output_tokens"] == 150

    def test_extract_token_usage_none(self):
        output = MagicMock()
        output.token_usage = None
        output.usage = None
        assert _extract_token_usage(output) == {}

    def test_estimate_cost_known_model(self):
        cost = _estimate_cost("gpt-4.1-mini", 1000, 500)
        assert cost > 0
        assert cost < 0.01

    def test_estimate_cost_unknown_model(self):
        cost = _estimate_cost("custom-model", 1000, 500)
        assert cost > 0


# -- Adapter creation --

class TestAdapterCreation:
    def test_adapter_init(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        assert adapter._crew is None
        assert adapter._run_counter == 0

    def test_adapter_detach_when_not_instrumented(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter.detach()  # Should not raise


# -- Kickoff wrapping (run lifecycle) --

class TestRunLifecycle:
    def test_kickoff_emits_run_started_and_completed(self, mock_pp):
        crew = _make_crew(name="My Crew")
        adapter = CrewAIAdapter(mock_pp)

        # Manually set up the adapter (skip import check)
        adapter._crew = crew
        adapter._original_kickoff = crew.kickoff
        crew.kickoff = adapter._wrapped_kickoff

        crew.kickoff()

        mock_pp.run_started.assert_called_once()
        call_args = mock_pp.run_started.call_args
        # run_started(run_id, name=...) — name can be positional or keyword
        all_args = list(call_args[0]) + list(call_args[1].values())
        assert any("My Crew" in str(a) for a in all_args)
        mock_pp.run_completed.assert_called_once()

    def test_kickoff_error_emits_run_error(self, mock_pp):
        crew = _make_crew()

        def failing_kickoff(*args, **kwargs):
            raise RuntimeError("API rate limit exceeded")

        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = crew
        adapter._original_kickoff = failing_kickoff
        crew.kickoff = adapter._wrapped_kickoff

        with pytest.raises(RuntimeError, match="API rate limit"):
            crew.kickoff()

        mock_pp.run_completed.assert_called_once()
        call_args = mock_pp.run_completed.call_args
        assert call_args[1].get("status") == "error" or call_args[0][1] == "error"

    def test_run_counter_increments(self, mock_pp):
        crew = _make_crew()
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = crew
        adapter._original_kickoff = crew.kickoff
        crew.kickoff = adapter._wrapped_kickoff

        crew.kickoff()
        crew.kickoff()

        assert adapter._run_counter == 2
        assert mock_pp.run_started.call_count == 2


# -- Step callback --

class TestStepCallback:
    def test_first_step_emits_agent_started(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        step = _make_step_output(agent_role="Researcher", thought="Planning research")
        adapter._on_step(step)

        mock_pp.agent_started.assert_called_once()
        assert mock_pp.agent_started.call_args[0][0] == "researcher"

    def test_subsequent_steps_do_not_re_emit_started(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        step1 = _make_step_output(agent_role="Researcher", thought="Step 1")
        step2 = _make_step_output(agent_role="Researcher", thought="Step 2")
        adapter._on_step(step1)
        adapter._on_step(step2)

        assert mock_pp.agent_started.call_count == 1
        assert mock_pp.agent_thinking.call_count == 2

    def test_thought_emits_agent_thinking(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        step = _make_step_output(agent_role="Writer", thought="Structuring the article")
        adapter._on_step(step)

        mock_pp.agent_thinking.assert_called()
        thought = mock_pp.agent_thinking.call_args[1]["thought"]
        assert "Structuring" in thought

    def test_tool_use_emits_thinking_with_tool_name(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        step = _make_step_output(
            agent_role="Researcher",
            tool="web_search",
            tool_input="AI frameworks 2026",
        )
        adapter._on_step(step)

        mock_pp.agent_thinking.assert_called()
        thought = mock_pp.agent_thinking.call_args[1]["thought"]
        assert "web_search" in thought
        assert "AI frameworks" in thought

    def test_tool_result_emits_artifact(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        step = _make_step_output(
            agent_role="Researcher",
            tool="calculator",
            result="42",
        )
        adapter._on_step(step)

        mock_pp.artifact_created.assert_called_once()
        content = mock_pp.artifact_created.call_args[1]["content"]
        assert "calculator" in content
        assert "42" in content

    def test_chains_to_original_callback(self, mock_pp):
        original_cb = MagicMock()
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()
        adapter._original_callbacks["step"] = original_cb

        step = _make_step_output(thought="test")
        adapter._on_step(step)

        original_cb.assert_called_once_with(step)

    def test_langchain_style_agent_action(self, mock_pp):
        """CrewAI sometimes wraps langchain AgentAction objects."""
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        step = MagicMock()
        agent = MagicMock()
        agent.role = "Researcher"
        step.agent = agent
        step.thought = None
        step.tool = None
        step.tool_input = None
        step.result = None
        step.text = None
        step.output = None

        # langchain-style action
        action = MagicMock()
        action.tool = "duckduckgo_search"
        action.tool_input = "latest news"
        step.action = action

        adapter._on_step(step)

        mock_pp.agent_thinking.assert_called()
        thought = mock_pp.agent_thinking.call_args[1]["thought"]
        assert "duckduckgo_search" in thought


# -- Task callback --

class TestTaskCallback:
    def test_task_complete_emits_agent_completed(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        output = _make_task_output(agent_role="Writer", raw="Blog post about AI")
        adapter._on_task_complete(output)

        mock_pp.agent_completed.assert_called_once()
        assert mock_pp.agent_completed.call_args[0][0] == "writer"
        assert "Blog post" in mock_pp.agent_completed.call_args[1]["output"]

    def test_task_complete_ensures_agent_started(self, mock_pp):
        """If task_callback fires without a prior step, agent_started should still emit."""
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        output = _make_task_output(agent_role="Reviewer")
        adapter._on_task_complete(output)

        mock_pp.agent_started.assert_called_once()
        assert mock_pp.agent_started.call_args[0][0] == "reviewer"

    def test_task_complete_with_token_usage(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        # Add an agent with a model to the crew
        agent_mock = MagicMock()
        agent_mock.llm = MagicMock()
        agent_mock.llm.model_name = "gpt-4.1"
        adapter._crew.agents = [agent_mock]

        output = _make_task_output(
            agent_role="Writer",
            token_usage={"prompt_tokens": 1000, "completion_tokens": 500},
        )
        adapter._on_task_complete(output)

        mock_pp.cost_update.assert_called_once()
        call_kw = mock_pp.cost_update.call_args[1]
        assert call_kw["tokens_in"] == 1000
        assert call_kw["tokens_out"] == 500
        assert call_kw["cost"] > 0
        assert call_kw["model"] == "gpt-4.1"

    def test_task_complete_chains_to_original(self, mock_pp):
        original_cb = MagicMock()
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()
        adapter._original_callbacks["task"] = original_cb

        output = _make_task_output()
        adapter._on_task_complete(output)

        original_cb.assert_called_once_with(output)

    def test_cost_accumulates_across_tasks(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()

        output1 = _make_task_output(
            agent_role="Researcher",
            token_usage={"prompt_tokens": 500, "completion_tokens": 200},
        )
        output2 = _make_task_output(
            agent_role="Writer",
            token_usage={"prompt_tokens": 800, "completion_tokens": 300},
        )

        adapter._on_task_complete(output1)
        adapter._on_task_complete(output2)

        assert adapter._accumulated_cost > 0
        assert mock_pp.cost_update.call_count == 2


# -- Detach --

class TestDetach:
    def test_detach_restores_callbacks(self, mock_pp):
        crew = _make_crew()
        original_step = MagicMock()
        original_task = MagicMock()
        crew.step_callback = original_step
        crew.task_callback = original_task

        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = crew
        adapter._original_callbacks = {"step": original_step, "task": original_task}
        adapter._original_kickoff = MagicMock()

        adapter.detach()

        assert crew.step_callback is original_step
        assert crew.task_callback is original_task
        assert adapter._crew is None

    def test_detach_clears_state(self, mock_pp):
        adapter = CrewAIAdapter(mock_pp)
        adapter._crew = _make_crew()
        adapter._seen_agents = {"agent-a", "agent-b"}
        adapter._accumulated_cost = 0.05

        adapter.detach()

        assert len(adapter._seen_agents) == 0
        assert adapter._accumulated_cost == 0.0
