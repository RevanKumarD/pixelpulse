"""E2E test: Real LangGraph pipeline visualized through PixelPulse.

This test creates an actual LangGraph StateGraph with three nodes
(researcher → writer → reviewer), instruments it with the PixelPulse
LangGraph adapter, runs the pipeline, and verifies that all expected
dashboard events flow through the event bus.

This is NOT a mock test — it exercises the full stack:
LangGraph graph.invoke → LangChain callbacks → PixelPulse adapter → EventBus
"""
from __future__ import annotations

import operator
from typing import Annotated, Any

import pytest

# -- LangGraph imports --
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

# -- PixelPulse imports --
from pixelpulse import PixelPulse
from pixelpulse.adapters.langgraph import LangGraphAdapter, PixelPulseCallbackHandler

# ---------------------------------------------------------------------------
# Pipeline State
# ---------------------------------------------------------------------------


class ResearchPipelineState(TypedDict):
    topic: str
    research: str
    draft: str
    review: str
    log: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# Real node functions (no mocks — these execute actual logic)
# ---------------------------------------------------------------------------


def researcher_node(state: ResearchPipelineState) -> dict[str, Any]:
    topic = state["topic"]
    research = (
        f"Research on '{topic}':\n"
        f"1. Market growing at 25% CAGR\n"
        f"2. Three major players dominate\n"
        f"3. Open-source adoption accelerating"
    )
    return {
        "research": research,
        "log": [f"researcher: analyzed '{topic}'"],
    }


def writer_node(state: ResearchPipelineState) -> dict[str, Any]:
    research = state["research"]
    draft = (
        "# Analysis Report\n\n"
        "## Summary\n"
        f"Based on research:\n{research}\n\n"
        "## Recommendation\n"
        "Invest in open-source tooling."
    )
    return {
        "draft": draft,
        "log": [f"writer: produced {len(draft)} chars"],
    }


def reviewer_node(state: ResearchPipelineState) -> dict[str, Any]:
    draft = state["draft"]
    review = f"Score: 9/10. Draft is {len(draft)} chars. Well structured."
    return {
        "review": review,
        "log": ["reviewer: scored 9/10"],
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    """Build and compile a real LangGraph StateGraph."""
    builder = StateGraph(ResearchPipelineState)
    builder.add_node("researcher", researcher_node)
    builder.add_node("writer", writer_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_edge("reviewer", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pp():
    """Create a PixelPulse instance configured for the test pipeline."""
    return PixelPulse(
        agents={
            "researcher": {"team": "research", "role": "Research Analyst"},
            "writer": {"team": "content", "role": "Technical Writer"},
            "reviewer": {"team": "quality", "role": "Reviewer"},
        },
        teams={
            "research": {"label": "Research", "color": "#00d4ff"},
            "content": {"label": "Content", "color": "#ff6ec7"},
            "quality": {"label": "Quality", "color": "#7cff6e"},
        },
        pipeline=["research", "writing", "review"],
        title="LangGraph E2E Test",
    )


@pytest.fixture
def graph():
    """Build and compile the LangGraph pipeline."""
    return build_graph()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLangGraphE2E:
    """Full end-to-end tests using a real LangGraph pipeline."""

    def test_graph_compiles_and_runs_without_pixelpulse(self, graph):
        """Sanity check: the graph works on its own."""
        result = graph.invoke({
            "topic": "AI Agents",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })
        assert result["research"] != ""
        assert result["draft"] != ""
        assert result["review"] != ""
        assert len(result["log"]) == 3

    def test_instrumented_graph_returns_same_result(self, pp, graph):
        """Instrumenting the graph should not change the pipeline output."""
        adapter = pp.adapter("langgraph")
        adapter.set_node_mapping({
            "researcher": "researcher",
            "writer": "writer",
            "reviewer": "reviewer",
        })
        adapter.instrument(graph)

        result = graph.invoke({
            "topic": "Multi-Agent Systems",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        assert "Multi-Agent Systems" in result["research"]
        assert "# Analysis Report" in result["draft"]
        assert "Score:" in result["review"]
        assert len(result["log"]) == 3

    def test_adapter_emits_agent_started_events(self, pp, graph):
        """Each node execution should emit agent_started."""
        started_calls: list[tuple[str, str]] = []
        original_started = pp.agent_started

        def capture_started(agent_id, task="", **kw):
            started_calls.append((agent_id, task))

        pp.agent_started = capture_started
        pp.agent_completed = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        adapter = pp.adapter("langgraph")
        adapter.set_node_mapping({
            "researcher": "researcher",
            "writer": "writer",
            "reviewer": "reviewer",
        })
        adapter.instrument(graph)

        graph.invoke({
            "topic": "Test Topic",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        agent_ids = [call[0] for call in started_calls]
        assert "researcher" in agent_ids
        assert "writer" in agent_ids
        assert "reviewer" in agent_ids

    def test_adapter_emits_agent_completed_events(self, pp, graph):
        """Each node should emit agent_completed with output."""
        completed_calls: list[tuple[str, str]] = []

        def capture_completed(agent_id, output="", **kw):
            completed_calls.append((agent_id, output))

        pp.agent_started = lambda *a, **kw: None
        pp.agent_completed = capture_completed
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        adapter = pp.adapter("langgraph")
        adapter.set_node_mapping({
            "researcher": "researcher",
            "writer": "writer",
            "reviewer": "reviewer",
        })
        adapter.instrument(graph)

        graph.invoke({
            "topic": "Observability",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        agent_ids = [call[0] for call in completed_calls]
        assert "researcher" in agent_ids
        assert "writer" in agent_ids
        assert "reviewer" in agent_ids

        # Verify output content is captured
        for agent_id, output in completed_calls:
            if agent_id == "researcher":
                assert "Observability" in output or "Research" in output or len(output) > 0
            elif agent_id == "reviewer":
                assert "Score" in output or "9/10" in output or len(output) > 0

    def test_run_lifecycle_events(self, pp, graph):
        """Adapter should emit run_started and run_completed."""
        run_events: list[tuple[str, str]] = []

        def capture_run_started(run_id, name="", **kw):
            run_events.append(("started", run_id))

        def capture_run_completed(run_id, status="", **kw):
            run_events.append(("completed", run_id))

        pp.agent_started = lambda *a, **kw: None
        pp.agent_completed = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = capture_run_started
        pp.run_completed = capture_run_completed

        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        graph.invoke({
            "topic": "Testing",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        assert len(run_events) >= 2
        assert run_events[0][0] == "started"
        assert run_events[-1][0] == "completed"
        # Same run_id for start and end
        assert run_events[0][1] == run_events[-1][1]

    def test_event_ordering(self, pp, graph):
        """Events should follow the pipeline order: researcher → writer → reviewer."""
        event_sequence: list[tuple[str, str]] = []

        def capture_started(agent_id, **kw):
            event_sequence.append(("started", agent_id))

        def capture_completed(agent_id, **kw):
            event_sequence.append(("completed", agent_id))

        pp.agent_started = capture_started
        pp.agent_completed = capture_completed
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        adapter = pp.adapter("langgraph")
        adapter.set_node_mapping({
            "researcher": "researcher",
            "writer": "writer",
            "reviewer": "reviewer",
        })
        adapter.instrument(graph)

        graph.invoke({
            "topic": "Event Ordering",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        # Extract just the agent-specific events (filter out any wrapper events)
        agent_events = [
            (ev, aid) for ev, aid in event_sequence
            if aid in ("researcher", "writer", "reviewer")
        ]

        # Find order of first started event for each agent
        started_order = [aid for ev, aid in agent_events if ev == "started"]
        # Remove duplicates keeping order
        seen = set()
        unique_order = []
        for aid in started_order:
            if aid not in seen:
                seen.add(aid)
                unique_order.append(aid)

        assert unique_order == ["researcher", "writer", "reviewer"]

    def test_detach_removes_instrumentation(self, pp, graph):
        """After detach(), the graph should run without emitting events."""
        call_count = {"started": 0}

        def count_started(agent_id, **kw):
            call_count["started"] += 1

        pp.agent_started = count_started
        pp.agent_completed = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        adapter = pp.adapter("langgraph")
        adapter.instrument(graph)

        # First run — should emit events
        graph.invoke({
            "topic": "First Run",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })
        first_run_count = call_count["started"]
        assert first_run_count > 0

        # Detach
        adapter.detach()

        # Reset counter
        call_count["started"] = 0

        # Second run — should NOT emit events
        result = graph.invoke({
            "topic": "Second Run",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        # Graph still works
        assert result["review"] != ""
        # But no events emitted
        assert call_count["started"] == 0

    def test_error_in_node_emits_error_event(self, pp):
        """If a node raises, the adapter should emit agent_error."""
        error_calls: list[tuple[str, str]] = []

        def capture_error(agent_id, error="", **kw):
            error_calls.append((agent_id, error))

        pp.agent_started = lambda *a, **kw: None
        pp.agent_completed = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = capture_error
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        # Build a graph with a failing node
        def failing_node(state):
            raise RuntimeError("Intentional test failure")

        builder = StateGraph(ResearchPipelineState)
        builder.add_node("researcher", failing_node)
        builder.add_edge(START, "researcher")
        builder.add_edge("researcher", END)
        failing_graph = builder.compile()

        adapter = pp.adapter("langgraph")
        adapter.instrument(failing_graph)

        with pytest.raises(RuntimeError, match="Intentional test failure"):
            failing_graph.invoke({
                "topic": "Will Fail",
                "research": "",
                "draft": "",
                "review": "",
                "log": [],
            })

        # Error event should have been emitted
        assert len(error_calls) >= 1
        assert any("Intentional test failure" in err for _, err in error_calls)

    def test_auto_detect_nodes(self, pp, graph):
        """Adapter should auto-detect nodes from compiled graph."""
        adapter = LangGraphAdapter(pp)
        adapter.instrument(graph)

        # Node mapping should be populated automatically
        assert "researcher" in adapter._node_to_agent
        assert "writer" in adapter._node_to_agent
        assert "reviewer" in adapter._node_to_agent

    def test_callback_handler_standalone(self, pp):
        """PixelPulseCallbackHandler can be used standalone with manual injection."""
        started_ids: list[str] = []

        def capture_started(agent_id, **kw):
            started_ids.append(agent_id)

        pp.agent_started = capture_started
        pp.agent_completed = lambda *a, **kw: None
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        graph = build_graph()
        handler = PixelPulseCallbackHandler(
            pp,
            node_to_agent={
                "researcher": "researcher",
                "writer": "writer",
                "reviewer": "reviewer",
            },
        )

        # Use manual callback injection (no adapter.instrument)
        result = graph.invoke(
            {
                "topic": "Manual Callbacks",
                "research": "",
                "draft": "",
                "review": "",
                "log": [],
            },
            config={"callbacks": [handler]},
        )

        assert result["review"] != ""
        assert "researcher" in started_ids
        assert "writer" in started_ids
        assert "reviewer" in started_ids


class TestLangGraphWithObserve:
    """Test the @observe decorator with LangGraph nodes."""

    def test_observe_wraps_node_functions(self, pp):
        """@observe decorator should work on LangGraph node functions."""
        from pixelpulse.decorators import observe

        events: list[tuple[str, str]] = []

        def capture_started(agent_id, **kw):
            events.append(("started", agent_id))

        def capture_completed(agent_id, **kw):
            events.append(("completed", agent_id))

        pp.agent_started = capture_started
        pp.agent_completed = capture_completed
        pp.agent_thinking = lambda *a, **kw: None
        pp.agent_error = lambda *a, **kw: None
        pp.artifact_created = lambda *a, **kw: None
        pp.cost_update = lambda *a, **kw: None
        pp.run_started = lambda *a, **kw: None
        pp.run_completed = lambda *a, **kw: None

        @observe(pp, as_type="agent", name="observed-researcher")
        def observed_researcher(state: ResearchPipelineState) -> dict[str, Any]:
            return {"research": "Observed research output", "log": ["observed"]}

        @observe(pp, as_type="agent", name="observed-writer")
        def observed_writer(state: ResearchPipelineState) -> dict[str, Any]:
            return {"draft": "Observed draft", "log": ["observed"]}

        builder = StateGraph(ResearchPipelineState)
        builder.add_node("researcher", observed_researcher)
        builder.add_node("writer", observed_writer)
        builder.add_edge(START, "researcher")
        builder.add_edge("researcher", "writer")
        builder.add_edge("writer", END)
        graph = builder.compile()

        result = graph.invoke({
            "topic": "Observe Test",
            "research": "",
            "draft": "",
            "review": "",
            "log": [],
        })

        assert result["draft"] == "Observed draft"

        agent_ids = [aid for _, aid in events]
        assert "observed-researcher" in agent_ids
        assert "observed-writer" in agent_ids
