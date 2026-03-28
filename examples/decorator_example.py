"""Decorator example — multi-agent pipeline using only @observe.

No framework required. Decorate plain Python functions and the PixelPulse
dashboard shows agent activity, tool calls, and parent-child relationships
in real time.

Run::

    python examples/decorator_example.py

Then open http://localhost:8765 in your browser.
"""
from __future__ import annotations

import threading
import time

from pixelpulse import PixelPulse
from pixelpulse.decorators import observe

pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Finds information"},
        "writer": {"team": "content", "role": "Writes articles"},
        "reviewer": {"team": "quality", "role": "Reviews output"},
    },
    teams={
        "research": {"label": "Research", "color": "#00d4ff"},
        "content": {"label": "Content", "color": "#ff6ec7"},
        "quality": {"label": "Quality", "color": "#39ff14"},
    },
    pipeline=["research", "content", "quality"],
)


@observe(pp, as_type="tool")
def web_search(query: str) -> str:
    time.sleep(0.5)
    return f"Found 3 results for: {query}"


@observe(pp, as_type="agent", name="researcher")
def research(topic: str) -> str:
    results = web_search(topic)
    time.sleep(1)
    return f"Research complete: {results}"


@observe(pp, as_type="agent", name="writer")
def write(brief: str) -> str:
    time.sleep(1.5)
    return f"Article written based on: {brief}"


@observe(pp, as_type="agent", name="reviewer")
def review(article: str) -> str:
    time.sleep(1)
    return "Approved: article meets quality standards"


def run_pipeline() -> None:
    """Execute the full research → write → review pipeline."""
    time.sleep(2)  # Wait for server to start

    pp.run_started("run-1", name="Content Pipeline")

    research_output = research("AI trends 2026")
    article = write(research_output)
    review_result = review(article)

    pp.run_completed("run-1", status="completed")

    print("\nPipeline complete!")
    print(f"  Research: {research_output[:60]}...")
    print(f"  Review:   {review_result}")
    print("\nDashboard at http://localhost:8765  (Ctrl-C to exit)")


if __name__ == "__main__":
    # Run the pipeline in a background thread so the server can start first
    t = threading.Thread(target=run_pipeline, daemon=True)
    t.start()

    pp.serve(port=8765, open_browser=True)
