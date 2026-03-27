#!/usr/bin/env python3
"""Example: Using PixelPulse with OpenTelemetry GenAI spans.

This example shows two integration paths:

1. **Python SDK path** — Attach ``PixelPulseSpanProcessor`` to a
   ``TracerProvider``. Every GenAI span is automatically converted to
   dashboard events.

2. **HTTP path** — Send OTLP JSON to ``POST /v1/traces``. Works from
   any language that speaks OTel.

Requirements::

    pip install pixelpulse[otel]

Run::

    python examples/otel_example.py
"""
from __future__ import annotations

import time

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import StatusCode

from pixelpulse import PixelPulse
from pixelpulse.otel import PixelPulseSpanProcessor

# ---- 1. Set up PixelPulse ----

pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Searches the web for information"},
        "writer": {"team": "content", "role": "Writes articles from research"},
        "reviewer": {"team": "qa", "role": "Reviews content for quality"},
    },
    teams={
        "research": {"label": "Research Team", "color": "#00d4ff"},
        "content": {"label": "Content Team", "color": "#ff6ec7"},
        "qa": {"label": "QA Team", "color": "#7c3aed"},
    },
    pipeline=["research", "writing", "review"],
    title="OTel GenAI Example",
)

# ---- 2. Set up OTel with PixelPulse processor ----

provider = TracerProvider()
provider.add_span_processor(PixelPulseSpanProcessor(pp))
tracer = provider.get_tracer("example.genai", "0.1.0")


# ---- 3. Simulate GenAI agent work using OTel spans ----

def simulate_agent_work() -> None:
    """Simulate a multi-agent workflow using OTel spans.

    Each span follows the OTel GenAI semantic conventions, with attributes
    like gen_ai.agent.name, gen_ai.request.model, gen_ai.usage.input_tokens.
    """
    # Researcher agent
    with tracer.start_as_current_span("gen_ai.agent.research") as span:
        span.set_attribute("gen_ai.agent.name", "researcher")
        span.set_attribute("gen_ai.request.model", "gpt-4o")
        span.set_attribute("gen_ai.usage.input_tokens", 150)
        span.set_attribute("gen_ai.usage.output_tokens", 800)
        time.sleep(0.5)  # Simulate work

        # Tool call within the agent
        with tracer.start_as_current_span("gen_ai.tool.web_search") as tool_span:
            tool_span.set_attribute("gen_ai.tool.name", "web_search")
            tool_span.set_attribute("gen_ai.tool.description", "Search the web for trends")
            time.sleep(0.2)

    time.sleep(0.3)

    # Writer agent
    with tracer.start_as_current_span("gen_ai.agent.write") as span:
        span.set_attribute("gen_ai.agent.name", "writer")
        span.set_attribute("gen_ai.request.model", "claude-sonnet-4-20250514")
        span.set_attribute("gen_ai.usage.input_tokens", 1200)
        span.set_attribute("gen_ai.usage.output_tokens", 2500)
        time.sleep(0.8)

    time.sleep(0.3)

    # Reviewer agent (simulating an error)
    with tracer.start_as_current_span("gen_ai.agent.review") as span:
        span.set_attribute("gen_ai.agent.name", "reviewer")
        span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
        span.set_status(StatusCode.ERROR, "Rate limit exceeded")
        time.sleep(0.2)


if __name__ == "__main__":
    import threading

    # Run the simulation in a background thread
    def run_simulation():
        time.sleep(3)  # Wait for server to start
        print("\n--- Starting OTel GenAI simulation ---\n")
        simulate_agent_work()
        print("\n--- Simulation complete. Check the dashboard! ---\n")

    sim_thread = threading.Thread(target=run_simulation, daemon=True)
    sim_thread.start()

    # Start the dashboard (blocking)
    pp.serve(port=8765, open_browser=True)
