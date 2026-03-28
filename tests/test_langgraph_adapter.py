"""Tests for the LangGraph adapter.

All LangGraph / LangChain imports are mocked so these tests run without
installing those packages.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pixelpulse.adapters.langgraph import LangGraphAdapter, PixelPulseCallbackHandler

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pp():
    """Return a mock PixelPulse instance with all emitter methods."""
    mock = MagicMock()
    mock.agent_started = MagicMock()
    mock.agent_completed = MagicMock()
    mock.agent_error = MagicMock()
    mock.agent_thinking = MagicMock()
    mock.agent_message = MagicMock()
    mock.artifact_created = MagicMock()
    mock.cost_update = MagicMock()
    mock.run_started = MagicMock()
    mock.run_completed = MagicMock()
    mock.stage_entered = MagicMock()
    mock.stage_exited = MagicMock()
    return mock


@pytest.fixture
def handler(pp):
    """Return a PixelPulseCallbackHandler wired to the mock PP."""
    return PixelPulseCallbackHandler(
        pp,
        node_to_agent={"research_node": "researcher", "writer_node": "writer"},
    )


@pytest.fixture
def adapter(pp):
    """Return a LangGraphAdapter wired to the mock PP."""
    return LangGraphAdapter(pp)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_compiled_graph(nodes: dict | None = None) -> MagicMock:
    """Create a mock compiled graph with invoke/ainvoke and nodes."""
    graph = MagicMock()
    graph.nodes = nodes or {"researcher": MagicMock(), "writer": MagicMock()}
    graph.invoke = MagicMock(return_value={"output": "done"})
    graph.ainvoke = MagicMock(return_value={"output": "done"})
    return graph


# ---------------------------------------------------------------------------
# Test: Adapter creation and instrumentation
# ---------------------------------------------------------------------------

class TestAdapterInstrumentation:
    def test_adapter_creation(self, adapter, pp):
        """Adapter stores the PixelPulse reference and starts with no graph."""
        assert adapter._pp is pp
        assert adapter._graph is None
        assert adapter._handler is None

    def test_instrument_patches_invoke(self, adapter):
        """instrument() should replace invoke on the compiled graph."""
        graph = _make_compiled_graph()
        original_invoke = graph.invoke

        adapter.instrument(graph)

        assert adapter._graph is graph
        assert adapter._handler is not None
        # invoke has been replaced with our patched version
        assert graph.invoke is not original_invoke
        assert adapter._original_invoke is original_invoke

    def test_instrument_auto_detects_nodes(self, adapter):
        """instrument() should discover node names from graph.nodes."""
        graph = _make_compiled_graph({
            "__start__": MagicMock(),
            "planner": MagicMock(),
            "executor": MagicMock(),
            "__end__": MagicMock(),
        })

        adapter.instrument(graph)

        # __start__ and __end__ should be excluded
        assert "planner" in adapter._node_to_agent
        assert "executor" in adapter._node_to_agent
        assert "__start__" not in adapter._node_to_agent
        assert "__end__" not in adapter._node_to_agent

    def test_set_node_mapping(self, adapter):
        """set_node_mapping should store the mapping and return self."""
        result = adapter.set_node_mapping({"a": "alpha", "b": "beta"})
        assert result is adapter
        assert adapter._node_to_agent == {"a": "alpha", "b": "beta"}

    def test_instrument_with_explicit_mapping(self, adapter):
        """Explicit node mappings take precedence over auto-detected ones."""
        adapter.set_node_mapping({"planner": "my-planner"})

        graph = _make_compiled_graph({"planner": MagicMock(), "coder": MagicMock()})
        adapter.instrument(graph)

        # Explicit mapping preserved
        assert adapter._node_to_agent["planner"] == "my-planner"
        # Auto-detected node added
        assert "coder" in adapter._node_to_agent


# ---------------------------------------------------------------------------
# Test: Callback handler translates events
# ---------------------------------------------------------------------------

class TestCallbackTranslation:
    def test_on_chain_start_emits_agent_started(self, handler, pp):
        """on_chain_start should call pp.agent_started."""
        rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"},
            inputs={"input": "Find trends"},
            run_id=rid,
        )

        pp.agent_started.assert_called_once()
        args = pp.agent_started.call_args
        assert args[0][0] == "researcher"  # mapped via node_to_agent
        assert "Find trends" in args[1]["task"]

    def test_on_chain_end_emits_agent_completed(self, handler, pp):
        """on_chain_end should call pp.agent_completed for a tracked chain."""
        rid = _make_run_id()
        # Start first so it's tracked
        handler.on_chain_start(
            serialized={"name": "writer_node"},
            inputs={},
            run_id=rid,
        )
        handler.on_chain_end(
            outputs={"output": "Article content here"},
            run_id=rid,
        )

        pp.agent_completed.assert_called_once()
        args = pp.agent_completed.call_args
        assert args[0][0] == "writer"
        assert "Article content here" in args[1]["output"]

    def test_on_chain_error_emits_agent_error(self, handler, pp):
        """on_chain_error should call pp.agent_error."""
        rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"},
            inputs={},
            run_id=rid,
        )
        handler.on_chain_error(
            error=RuntimeError("connection timeout"),
            run_id=rid,
        )

        pp.agent_error.assert_called_once()
        args = pp.agent_error.call_args
        assert args[0][0] == "researcher"
        assert "connection timeout" in args[1]["error"]

    def test_on_llm_start_emits_thinking(self, handler, pp):
        """on_llm_start should emit an agent_thinking event."""
        parent_rid = _make_run_id()
        # Register the parent chain first
        handler.on_chain_start(
            serialized={"name": "research_node"},
            inputs={},
            run_id=parent_rid,
        )

        llm_rid = _make_run_id()
        handler.on_llm_start(
            serialized={"name": "gpt-4o"},
            prompts=["Tell me about AI agents"],
            run_id=llm_rid,
            parent_run_id=parent_rid,
        )

        # agent_thinking called at least once (chain start may also trigger)
        thinking_calls = pp.agent_thinking.call_args_list
        assert len(thinking_calls) >= 1
        # The LLM-related thinking call should mention gpt-4o
        llm_call = thinking_calls[-1]
        assert "gpt-4o" in llm_call[1]["thought"]

    def test_on_llm_end_emits_cost_update(self, handler, pp):
        """on_llm_end with token usage should emit a cost_update."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"},
            inputs={},
            run_id=parent_rid,
        )

        llm_rid = _make_run_id()
        handler.on_llm_start(
            serialized={"name": "gpt-4o"},
            prompts=["Hello"],
            run_id=llm_rid,
            parent_run_id=parent_rid,
        )

        # Simulate LLMResult with token usage
        llm_result = SimpleNamespace(
            llm_output={
                "token_usage": {
                    "prompt_tokens": 150,
                    "completion_tokens": 300,
                },
                "model_name": "gpt-4o",
            }
        )
        handler.on_llm_end(response=llm_result, run_id=llm_rid)

        pp.cost_update.assert_called_once()
        args = pp.cost_update.call_args
        assert args[0][0] == "researcher"
        assert args[1]["tokens_in"] == 150
        assert args[1]["tokens_out"] == 300
        assert args[1]["model"] == "gpt-4o"

    def test_on_tool_start_end_emits_thinking_and_artifact(self, handler, pp):
        """Tool start/end should emit thinking + artifact_created."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"},
            inputs={},
            run_id=parent_rid,
        )

        tool_rid = _make_run_id()
        handler.on_tool_start(
            serialized={"name": "web_search"},
            input_str="AI agent frameworks",
            run_id=tool_rid,
            parent_run_id=parent_rid,
        )

        pp.agent_thinking.assert_called()
        last_thought = pp.agent_thinking.call_args_list[-1]
        assert "web_search" in last_thought[1]["thought"]

        handler.on_tool_end(
            output="Found 10 results",
            run_id=tool_rid,
        )

        pp.artifact_created.assert_called_once()
        args = pp.artifact_created.call_args
        assert args[0][0] == "researcher"
        assert args[1]["artifact_type"] == "tool_output"

    def test_langgraph_node_metadata(self, handler, pp):
        """When metadata contains langgraph_node, use it for agent resolution."""
        rid = _make_run_id()
        handler.on_chain_start(
            serialized={},
            inputs={"input": "test"},
            run_id=rid,
            metadata={"langgraph_node": "research_node"},
        )

        pp.agent_started.assert_called_once()
        assert pp.agent_started.call_args[0][0] == "researcher"


# ---------------------------------------------------------------------------
# Test: Detach / cleanup
# ---------------------------------------------------------------------------

class TestDetach:
    def test_detach_restores_invoke(self, adapter):
        """detach() should restore the original invoke method."""
        graph = _make_compiled_graph()
        original_invoke = graph.invoke

        adapter.instrument(graph)
        assert graph.invoke is not original_invoke

        adapter.detach()
        assert graph.invoke is original_invoke
        assert adapter._graph is None
        assert adapter._handler is None

    def test_detach_without_instrument_is_safe(self, adapter):
        """detach() when nothing was instrumented should not raise."""
        adapter.detach()
        assert adapter._graph is None

    def test_double_detach_is_safe(self, adapter):
        """Calling detach() twice should not raise."""
        graph = _make_compiled_graph()
        adapter.instrument(graph)
        adapter.detach()
        adapter.detach()
        assert adapter._graph is None


# ---------------------------------------------------------------------------
# Test: Token tracking
# ---------------------------------------------------------------------------

class TestTokenTracking:
    def test_no_cost_update_without_usage(self, handler, pp):
        """If LLM response has no token usage, cost_update should not fire."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"}, inputs={}, run_id=parent_rid,
        )

        llm_rid = _make_run_id()
        handler.on_llm_start(
            serialized={}, prompts=["hi"], run_id=llm_rid, parent_run_id=parent_rid,
        )

        # Response with no llm_output
        handler.on_llm_end(response=SimpleNamespace(llm_output=None), run_id=llm_rid)

        pp.cost_update.assert_not_called()

    def test_cost_update_with_alternative_keys(self, handler, pp):
        """Token usage with input_tokens/output_tokens keys should also work."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"}, inputs={}, run_id=parent_rid,
        )

        llm_rid = _make_run_id()
        handler.on_llm_start(
            serialized={}, prompts=["test"], run_id=llm_rid, parent_run_id=parent_rid,
        )

        llm_result = SimpleNamespace(
            llm_output={
                "usage": {"input_tokens": 50, "output_tokens": 100},
                "model": "claude-sonnet-4-20250514",
            }
        )
        handler.on_llm_end(response=llm_result, run_id=llm_rid)

        pp.cost_update.assert_called_once()
        args = pp.cost_update.call_args
        assert args[1]["tokens_in"] == 50
        assert args[1]["tokens_out"] == 100
        assert args[1]["model"] == "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_agent_name_uses_fallback(self, pp):
        """When no name is available, fallback to 'unknown-agent'."""
        handler = PixelPulseCallbackHandler(pp, node_to_agent={})
        rid = _make_run_id()
        handler.on_chain_start(
            serialized={},
            inputs={},
            run_id=rid,
        )

        pp.agent_started.assert_called_once()
        assert pp.agent_started.call_args[0][0] == "unknown-agent"

    def test_chain_end_without_start_ignored(self, handler, pp):
        """on_chain_end for an untracked run_id should not crash."""
        rid = _make_run_id()
        handler.on_chain_end(outputs={"output": "orphan"}, run_id=rid)
        # No agent_completed should fire for untracked chain
        pp.agent_completed.assert_not_called()

    def test_llm_error_without_start(self, handler, pp):
        """on_llm_error for an untracked LLM should still emit error."""
        rid = _make_run_id()
        handler.on_llm_error(
            error=RuntimeError("rate limited"),
            run_id=rid,
        )
        pp.agent_error.assert_called_once()
        assert "rate limited" in pp.agent_error.call_args[1]["error"]

    def test_tool_error_emits_agent_error(self, handler, pp):
        """on_tool_error should emit agent_error."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"}, inputs={}, run_id=parent_rid,
        )

        tool_rid = _make_run_id()
        handler.on_tool_error(
            error=ValueError("invalid input"),
            run_id=tool_rid,
            parent_run_id=parent_rid,
        )

        pp.agent_error.assert_called_once()
        assert "invalid input" in pp.agent_error.call_args[1]["error"]

    def test_create_callbacks_returns_handler_list(self, adapter):
        """create_callbacks() should return a list with one handler."""
        callbacks = adapter.create_callbacks()
        assert isinstance(callbacks, list)
        assert len(callbacks) == 1
        assert isinstance(callbacks[0], PixelPulseCallbackHandler)

    def test_patched_invoke_calls_original_and_emits_run_events(self, adapter, pp):
        """Patched invoke should call original, emit run_started/completed."""
        graph = _make_compiled_graph()
        adapter.instrument(graph)

        result = graph.invoke({"input": "test"})

        # Original invoke was called
        adapter._original_invoke.assert_called_once()
        # run_started and run_completed emitted
        pp.run_started.assert_called_once()
        pp.run_completed.assert_called_once()
        assert pp.run_completed.call_args[1]["status"] == "completed"

    def test_patched_invoke_emits_failed_on_error(self, adapter, pp):
        """If the original invoke raises, run_completed status should be 'failed'."""
        graph = _make_compiled_graph()
        graph.invoke = MagicMock(side_effect=RuntimeError("graph exploded"))
        adapter.instrument(graph)

        with pytest.raises(RuntimeError, match="graph exploded"):
            graph.invoke({"input": "test"})

        pp.run_completed.assert_called_once()
        assert pp.run_completed.call_args[1]["status"] == "failed"

    def test_agent_action_and_finish(self, handler, pp):
        """on_agent_action / on_agent_finish should emit thinking / completed."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"}, inputs={}, run_id=parent_rid,
        )

        action = SimpleNamespace(tool="web_search", tool_input="query text")
        handler.on_agent_action(action=action, parent_run_id=parent_rid)

        thinking_calls = pp.agent_thinking.call_args_list
        assert any("web_search" in c[1]["thought"] for c in thinking_calls)

        finish = SimpleNamespace(return_values={"output": "final answer"})
        handler.on_agent_finish(finish=finish, parent_run_id=parent_rid)

        completed_calls = pp.agent_completed.call_args_list
        assert any("final answer" in c[1]["output"] for c in completed_calls)

    def test_retriever_callbacks(self, handler, pp):
        """Retriever start/end/error should emit appropriate events."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "research_node"}, inputs={}, run_id=parent_rid,
        )

        handler.on_retriever_start(
            serialized={}, query="AI agents", parent_run_id=parent_rid,
        )
        pp.agent_thinking.assert_called()

        mock_docs = [MagicMock(), MagicMock(), MagicMock()]
        handler.on_retriever_end(documents=mock_docs, parent_run_id=parent_rid)
        pp.artifact_created.assert_called_once()
        assert "3 documents" in pp.artifact_created.call_args[1]["content"]

    def test_on_chat_model_start(self, handler, pp):
        """on_chat_model_start should also emit thinking."""
        parent_rid = _make_run_id()
        handler.on_chain_start(
            serialized={"name": "writer_node"}, inputs={}, run_id=parent_rid,
        )

        chat_rid = _make_run_id()
        handler.on_chat_model_start(
            serialized={"name": "claude-sonnet"},
            messages=[[MagicMock()]],
            run_id=chat_rid,
            parent_run_id=parent_rid,
        )

        thinking_calls = pp.agent_thinking.call_args_list
        assert any("claude-sonnet" in c[1]["thought"] for c in thinking_calls)
