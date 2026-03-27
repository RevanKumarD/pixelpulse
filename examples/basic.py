"""Basic PixelPulse example — shows a simple 4-agent system.

Run with: python examples/basic.py
Then open http://localhost:8765 in your browser.
"""
import threading
import time

from pixelpulse import PixelPulse

# Configure your agents and teams
pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Searches for market trends"},
        "analyst": {"team": "research", "role": "Analyzes data patterns"},
        "writer": {"team": "content", "role": "Writes product descriptions"},
        "reviewer": {"team": "quality", "role": "Reviews output quality"},
    },
    teams={
        "research": {"label": "Research Lab", "color": "#00d4ff", "icon": "🔬"},
        "content": {"label": "Content Studio", "color": "#ff6ec7", "icon": "📝"},
        "quality": {"label": "QA Center", "color": "#ffae00", "icon": "✅"},
    },
    pipeline=["research", "content", "quality"],
    title="Basic Example",
)


def simulate_agents():
    """Simulate agent activity after a short delay."""
    time.sleep(3)  # Wait for server + browser to start

    # Research phase
    pp.run_started("run_001", name="Market Analysis")
    pp.stage_entered("research", run_id="run_001")

    pp.agent_started("researcher", task="Scanning Google Trends for Q2 2026")
    time.sleep(2)
    pp.agent_thinking("researcher", thought="Found 3 trending topics in sustainable fashion")
    time.sleep(1)
    pp.agent_message("researcher", "analyst", content="3 trends found: eco-denim, recycled sneakers, hemp basics", tag="signals")
    pp.cost_update("researcher", cost=0.002, tokens_in=800, tokens_out=200, model="gpt-4.1-mini")
    pp.agent_completed("researcher", output="Identified 3 trending topics in sustainable fashion for Q2 2026")
    time.sleep(1)

    pp.agent_started("analyst", task="Scoring market viability")
    time.sleep(2)
    pp.agent_thinking("analyst", thought="Eco-denim scores 8.5/10 — high demand, low competition")
    pp.agent_message("analyst", "writer", content="Top pick: eco-denim (score: 8.5/10)", tag="scores")
    pp.cost_update("analyst", cost=0.003, tokens_in=1200, tokens_out=400, model="gpt-4.1-mini")
    pp.agent_completed("analyst", output="Market analysis complete. Eco-denim has highest viability score.")
    pp.stage_exited("research", run_id="run_001")
    time.sleep(1)

    # Content phase
    pp.stage_entered("content", run_id="run_001")
    pp.agent_started("writer", task="Writing product listing for eco-denim jacket")
    time.sleep(3)
    pp.agent_thinking("writer", thought="Crafting compelling description targeting eco-conscious millennials")
    pp.artifact_created("writer", artifact_type="text", content="Eco-Denim Jacket — Sustainable style meets everyday comfort...")
    pp.cost_update("writer", cost=0.005, tokens_in=2000, tokens_out=800, model="claude-sonnet-4-6")
    pp.agent_completed("writer", output="Product listing complete with SEO-optimized title and description")
    pp.stage_exited("content", run_id="run_001")
    time.sleep(1)

    # QA phase
    pp.stage_entered("quality", run_id="run_001")
    pp.agent_started("reviewer", task="Quality review of listing")
    time.sleep(2)
    pp.agent_thinking("reviewer", thought="Checking grammar, brand voice, and marketplace compliance")
    pp.agent_message("reviewer", "writer", content="Minor fix: add size chart reference", tag="feedback")
    pp.cost_update("reviewer", cost=0.001, tokens_in=600, tokens_out=100, model="gpt-4.1-mini")
    pp.agent_completed("reviewer", output="QA passed with 1 minor suggestion. Listing ready for publish.")
    pp.stage_exited("quality", run_id="run_001")

    pp.run_completed("run_001", status="completed", total_cost=0.011)
    print("\n  Simulation complete! Check the dashboard.")


if __name__ == "__main__":
    # Start the simulation in a background thread
    sim_thread = threading.Thread(target=simulate_agents, daemon=True)
    sim_thread.start()

    # Start the dashboard server (blocking)
    pp.serve()
