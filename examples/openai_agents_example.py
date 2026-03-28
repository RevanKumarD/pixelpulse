"""OpenAI Agents SDK + PixelPulse example.

Demonstrates a multi-agent triage system where:
- A triage agent routes questions to specialists
- A research agent handles factual questions
- A creative agent handles writing tasks
- Handoffs between agents are visualized in the dashboard

Run with:
    pip install pixelpulse[openai]
    export OPENAI_API_KEY=sk-...
    python examples/openai_agents_example.py

Then open http://localhost:8765 in your browser.

If you don't have an API key, the example falls back to a simulation
that demonstrates the same dashboard events without making real API calls.
"""
import os
import sys
import threading
import time

from pixelpulse import PixelPulse

# ── Configure PixelPulse ──────────────────────────────────────────────

pp = PixelPulse(
    agents={
        "triage-agent": {"team": "routing", "role": "Routes questions to specialists"},
        "research-agent": {"team": "research", "role": "Answers factual questions"},
        "creative-agent": {"team": "creative", "role": "Writes creative content"},
    },
    teams={
        "routing": {"label": "Triage", "color": "#ffae00", "icon": "🔀"},
        "research": {"label": "Research", "color": "#00d4ff", "icon": "🔬"},
        "creative": {"label": "Creative", "color": "#ff6ec7", "icon": "✨"},
    },
    pipeline=["routing", "research", "creative"],
    title="OpenAI Agents — Triage System",
)


def run_with_real_sdk():
    """Run with the actual OpenAI Agents SDK (requires openai-agents + API key)."""
    from agents import Agent, Runner

    # 1. Instrument — registers our tracing processor globally
    adapter = pp.adapter("openai")
    adapter.instrument()

    # 2. Define agents with handoffs
    research_agent = Agent(
        name="research-agent",
        instructions="You are a research assistant. Answer factual questions concisely.",
    )

    creative_agent = Agent(
        name="creative-agent",
        instructions="You are a creative writer. Write engaging, imaginative content.",
    )

    triage_agent = Agent(
        name="triage-agent",
        instructions=(
            "You are a triage agent. Route factual questions to research-agent "
            "and creative requests to creative-agent."
        ),
        handoffs=[research_agent, creative_agent],
    )

    # 3. Run the triage system
    print("\n  Running triage agent with real OpenAI API...")
    result = Runner.run_sync(
        triage_agent,
        "Write me a haiku about artificial intelligence",
    )
    print(f"\n  Result: {result.final_output}")

    # Run another query to show routing
    result2 = Runner.run_sync(
        triage_agent,
        "What is the speed of light in km/s?",
    )
    print(f"\n  Result: {result2.final_output}")

    adapter.detach()


def run_simulation():
    """Simulate OpenAI Agents SDK events without a real API key."""
    time.sleep(3)  # Wait for server to start

    run_id = "openai-demo-001"
    pp.run_started(run_id, name="Triage Demo")

    # ── Triage agent receives the question ──
    pp.stage_entered("routing", run_id=run_id)
    pp.agent_started("triage-agent", task="Route: 'Write a haiku about AI'")
    time.sleep(1.5)
    pp.agent_thinking("triage-agent", thought="This is a creative writing request")
    pp.cost_update("triage-agent", cost=0.0003, tokens_in=150, tokens_out=30, model="gpt-4.1-mini")
    time.sleep(1)

    # Handoff to creative agent
    pp.agent_message(
        "triage-agent", "creative-agent",
        content="Handoff: creative writing request — write a haiku about AI",
        tag="handoff",
    )
    pp.agent_completed("triage-agent", output="Routed to creative-agent")
    pp.stage_exited("routing", run_id=run_id)
    time.sleep(1)

    # ── Creative agent writes the haiku ──
    pp.stage_entered("creative", run_id=run_id)
    pp.agent_started("creative-agent", task="Write a haiku about artificial intelligence")
    time.sleep(2)
    pp.agent_thinking("creative-agent", thought="Composing haiku with 5-7-5 syllable structure...")
    time.sleep(1.5)
    pp.agent_thinking("creative-agent", thought="Silicon dreams flow / Through circuits of endless thought / Wisdom without breath")
    pp.cost_update("creative-agent", cost=0.002, tokens_in=400, tokens_out=120, model="gpt-4.1")
    time.sleep(1)
    pp.artifact_created("creative-agent", artifact_type="text", content="Silicon dreams flow / Through circuits of endless thought / Wisdom without breath")
    pp.agent_completed("creative-agent", output="Haiku: Silicon dreams flow / Through circuits of endless thought / Wisdom without breath")
    pp.stage_exited("creative", run_id=run_id)
    time.sleep(1.5)

    # ── Second query: factual — routed to research ──
    pp.stage_entered("routing", run_id=run_id)
    pp.agent_started("triage-agent", task="Route: 'What is the speed of light?'")
    time.sleep(1)
    pp.agent_thinking("triage-agent", thought="This is a factual question — routing to research")
    pp.cost_update("triage-agent", cost=0.0002, tokens_in=100, tokens_out=20, model="gpt-4.1-mini")
    pp.agent_message(
        "triage-agent", "research-agent",
        content="Handoff: factual question — what is the speed of light?",
        tag="handoff",
    )
    pp.agent_completed("triage-agent", output="Routed to research-agent")
    pp.stage_exited("routing", run_id=run_id)
    time.sleep(1)

    pp.stage_entered("research", run_id=run_id)
    pp.agent_started("research-agent", task="Answer: What is the speed of light in km/s?")
    time.sleep(2)
    pp.agent_thinking("research-agent", thought="The speed of light in vacuum is approximately 299,792.458 km/s")
    pp.cost_update("research-agent", cost=0.001, tokens_in=200, tokens_out=80, model="gpt-4.1")
    time.sleep(1)
    pp.agent_completed("research-agent", output="The speed of light is approximately 299,792 km/s")
    pp.stage_exited("research", run_id=run_id)

    total_cost = 0.0003 + 0.002 + 0.0002 + 0.001
    pp.run_completed(run_id, status="completed", total_cost=total_cost)
    print("\n  Simulation complete! Check the dashboard at http://localhost:8765")


if __name__ == "__main__":
    has_sdk = False
    has_key = bool(os.environ.get("OPENAI_API_KEY"))

    try:
        import agents  # noqa: F401
        has_sdk = True
    except (ImportError, Exception):
        # ImportError: package not installed
        # Other exceptions: SDK version incompatible with this Python version
        #   (e.g. KeyError from typing on Python 3.11)
        pass

    if has_sdk and has_key:
        # Real SDK mode
        sim_thread = threading.Thread(target=run_with_real_sdk, daemon=True)
    else:
        if not has_sdk:
            print("  openai-agents SDK not available -- running simulation mode")
            print("  (requires: pip install openai-agents, Python 3.12+)")
        elif not has_key:
            print("  OPENAI_API_KEY not set -- running simulation mode")
        sim_thread = threading.Thread(target=run_simulation, daemon=True)

    sim_thread.start()
    pp.serve()
