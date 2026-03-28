"""LangGraph + PixelPulse example.

A runnable multi-agent pipeline that demonstrates PixelPulse instrumentation
with LangGraph.  The pipeline has three nodes — researcher, writer, reviewer —
connected in a linear graph.

Requirements:
    pip install pixelpulse langgraph langchain-core

If you do NOT have an OpenAI / Anthropic key you can still run this example:
it uses a lightweight fake LLM that returns canned responses so the graph
executes end-to-end and events flow to the dashboard.

Run:
    python examples/langgraph_example.py

Then open http://localhost:8765 in your browser to see the pixel-art dashboard.
"""
from __future__ import annotations

import operator
import threading
import time
from typing import Annotated, Any

# -- LangGraph imports ------------------------------------------------------
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

# -- PixelPulse imports -----------------------------------------------------
from pixelpulse import PixelPulse

# ---------------------------------------------------------------------------
# 1. Define the shared state
# ---------------------------------------------------------------------------
# Each node reads from and writes to this typed dict.  The ``log`` field uses
# an append-only reducer so every node's output is accumulated.


class PipelineState(TypedDict):
    topic: str
    research: str
    draft: str
    review: str
    log: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# 2. Define node functions (using fake / simulated LLM calls)
# ---------------------------------------------------------------------------
# In a real project you would replace the sleep + canned response with an
# actual LLM call (e.g. ``ChatOpenAI(...).invoke(...)``).


def researcher_node(state: PipelineState) -> dict[str, Any]:
    """Simulate a research agent gathering information on the topic."""
    topic = state["topic"]
    # Simulate LLM thinking time
    time.sleep(1.5)
    research_output = (
        f"Research findings on '{topic}':\n"
        f"1. Market size is projected to reach $50B by 2028.\n"
        f"2. Key players include AlphaCorp, BetaLabs, and GammaTech.\n"
        f"3. Growth is driven by increasing enterprise adoption.\n"
        f"4. Regulatory landscape remains fragmented across regions."
    )
    return {
        "research": research_output,
        "log": [f"researcher: completed research on '{topic}'"],
    }


def writer_node(state: PipelineState) -> dict[str, Any]:
    """Simulate a writer agent drafting an article from the research."""
    research = state["research"]
    time.sleep(2.0)
    draft = (
        "# Industry Analysis Report\n\n"
        "## Executive Summary\n"
        "The market is experiencing rapid growth driven by enterprise adoption. "
        "Three dominant players — AlphaCorp, BetaLabs, and GammaTech — are "
        "competing for market share in a $50B opportunity.\n\n"
        "## Key Findings\n"
        f"{research}\n\n"
        "## Recommendations\n"
        "Focus on the enterprise segment and monitor regulatory changes."
    )
    return {
        "draft": draft,
        "log": [f"writer: drafted {len(draft)} chars"],
    }


def reviewer_node(state: PipelineState) -> dict[str, Any]:
    """Simulate a reviewer agent scoring the draft."""
    draft = state["draft"]
    time.sleep(1.0)
    review = (
        "Review score: 8.5/10\n"
        "Strengths: Clear structure, good data coverage.\n"
        "Suggestions: Add competitor comparison table, cite sources."
    )
    return {
        "review": review,
        "log": [f"reviewer: scored draft ({len(draft)} chars) at 8.5/10"],
    }


# ---------------------------------------------------------------------------
# 3. Build the LangGraph StateGraph
# ---------------------------------------------------------------------------

builder = StateGraph(PipelineState)

# Add nodes
builder.add_node("researcher", researcher_node)
builder.add_node("writer", writer_node)
builder.add_node("reviewer", reviewer_node)

# Wire edges: START -> researcher -> writer -> reviewer -> END
builder.add_edge(START, "researcher")
builder.add_edge("researcher", "writer")
builder.add_edge("writer", "reviewer")
builder.add_edge("reviewer", END)

# Compile
graph = builder.compile()

# ---------------------------------------------------------------------------
# 4. Configure PixelPulse
# ---------------------------------------------------------------------------

pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Senior Research Analyst"},
        "writer": {"team": "content", "role": "Technical Writer"},
        "reviewer": {"team": "quality", "role": "Editorial Reviewer"},
    },
    teams={
        "research": {"label": "Research", "color": "#00d4ff"},
        "content": {"label": "Content", "color": "#ff6ec7"},
        "quality": {"label": "Quality", "color": "#7cff6e"},
    },
    pipeline=["research", "writing", "review"],
    title="LangGraph Demo",
)

# ---------------------------------------------------------------------------
# 5. Instrument the compiled graph
# ---------------------------------------------------------------------------

adapter = pp.adapter("langgraph")

# Optional: explicitly map node names to agent IDs (useful when names differ)
adapter.set_node_mapping({
    "researcher": "researcher",
    "writer": "writer",
    "reviewer": "reviewer",
})

adapter.instrument(graph)

# ---------------------------------------------------------------------------
# 6. Run everything
# ---------------------------------------------------------------------------


def run_pipeline() -> None:
    """Execute the graph after giving the dashboard a moment to start."""
    # Wait for the dashboard server to be ready
    time.sleep(3)
    print("\n--- Running LangGraph pipeline ---\n")

    result = graph.invoke({
        "topic": "AI Agent Frameworks",
        "research": "",
        "draft": "",
        "review": "",
        "log": [],
    })

    print("\n--- Pipeline complete ---")
    print(f"Log entries: {result['log']}")
    print(f"\nReview:\n{result['review']}")
    print("\nDashboard is still running at http://localhost:8765")
    print("Press Ctrl+C to stop.")


if __name__ == "__main__":
    # Start the pipeline in a background thread
    pipeline_thread = threading.Thread(target=run_pipeline, daemon=True)
    pipeline_thread.start()

    # Start the dashboard (blocking) — open http://localhost:8765
    print("Starting PixelPulse dashboard at http://localhost:8765 ...")
    pp.serve(port=8765, open_browser=True)
