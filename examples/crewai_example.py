"""CrewAI + PixelPulse example.

Demonstrates a multi-agent research crew where:
- A researcher investigates a topic using tools
- A writer creates content based on research
- A reviewer provides quality feedback
- Task completions and tool usage are visualized in the dashboard

Run with:
    pip install pixelpulse[crewai]
    export OPENAI_API_KEY=sk-...
    python examples/crewai_example.py

Then open http://localhost:8765 in your browser.

If you don't have CrewAI installed or an API key, the example falls back
to a simulation that demonstrates the same dashboard events.
"""
import os
import sys
import threading
import time

from pixelpulse import PixelPulse

# -- Configure PixelPulse --

pp = PixelPulse(
    agents={
        "senior-researcher": {"team": "research", "role": "Senior Research Analyst"},
        "content-writer": {"team": "content", "role": "Technical Content Writer"},
        "quality-reviewer": {"team": "review", "role": "Quality Assurance Reviewer"},
    },
    teams={
        "research": {"label": "Research", "color": "#00d4ff", "icon": "\ud83d\udd2c"},
        "content": {"label": "Content", "color": "#ff6ec7", "icon": "\u270d\ufe0f"},
        "review": {"label": "Review", "color": "#00ff88", "icon": "\u2705"},
    },
    pipeline=["research", "content", "review"],
    title="CrewAI \u2014 Research & Writing Crew",
)


def run_with_real_crewai():
    """Run with the actual CrewAI SDK (requires crewai + API key)."""
    from crewai import Agent, Task, Crew

    # 1. Instrument the crew
    adapter = pp.adapter("crewai")

    # 2. Define agents
    researcher = Agent(
        role="Senior Researcher",
        goal="Find the most relevant information about AI agent frameworks",
        backstory="Expert technology analyst with deep knowledge of AI systems.",
        verbose=True,
    )

    writer = Agent(
        role="Content Writer",
        goal="Write a compelling summary of the research findings",
        backstory="Experienced technical writer who makes complex topics accessible.",
        verbose=True,
    )

    reviewer = Agent(
        role="Quality Reviewer",
        goal="Review the content for accuracy and clarity",
        backstory="Meticulous editor with a keen eye for detail.",
        verbose=True,
    )

    # 3. Define tasks
    research_task = Task(
        description=(
            "Research the current state of AI agent frameworks in 2026. "
            "Compare CrewAI, LangGraph, AutoGen, and OpenAI Agents SDK."
        ),
        expected_output="A structured comparison of the top 4 agent frameworks.",
        agent=researcher,
    )

    writing_task = Task(
        description="Write a concise blog post summarizing the research findings.",
        expected_output="A 500-word blog post about AI agent frameworks.",
        agent=writer,
    )

    review_task = Task(
        description="Review the blog post for accuracy, clarity, and engagement.",
        expected_output="Reviewed blog post with improvement suggestions.",
        agent=reviewer,
    )

    # 4. Create and instrument the crew
    crew = Crew(
        agents=[researcher, writer, reviewer],
        tasks=[research_task, writing_task, review_task],
        verbose=True,
    )
    adapter.instrument(crew)

    # 5. Run the crew
    print("\n  Running CrewAI crew with real API...")
    result = crew.kickoff()
    print(f"\n  Result preview: {str(result)[:200]}")

    adapter.detach()


def run_simulation():
    """Simulate CrewAI events without a real API key."""
    time.sleep(3)  # Wait for server to start

    run_id = "crewai-demo-001"
    pp.run_started(run_id, name="Research & Writing Crew")

    # -- Stage 1: Research --
    pp.stage_entered("research", run_id=run_id)
    pp.agent_started(
        "senior-researcher",
        task="Research AI agent frameworks in 2026: CrewAI, LangGraph, AutoGen, OpenAI Agents SDK",
    )
    time.sleep(2)

    pp.agent_thinking(
        "senior-researcher",
        thought="Planning research approach: compare architecture, ease of use, and ecosystem",
    )
    time.sleep(1.5)

    pp.agent_thinking(
        "senior-researcher",
        thought="Using tool: web_search(AI agent framework comparison 2026)",
    )
    time.sleep(2)

    pp.artifact_created(
        "senior-researcher",
        artifact_type="tool_result",
        content="web_search: Found 15 relevant articles on AI agent frameworks...",
    )
    time.sleep(1)

    pp.agent_thinking(
        "senior-researcher",
        thought="CrewAI focuses on role-based collaboration, LangGraph on stateful graphs, "
        "AutoGen on event-driven messaging, OpenAI SDK on native tool calling",
    )
    pp.cost_update(
        "senior-researcher",
        cost=0.005,
        tokens_in=2000,
        tokens_out=800,
        model="gpt-4.1",
    )
    time.sleep(1.5)

    pp.agent_thinking(
        "senior-researcher",
        thought="Using tool: web_search(CrewAI vs LangGraph performance benchmarks)",
    )
    time.sleep(1.5)

    pp.artifact_created(
        "senior-researcher",
        artifact_type="tool_result",
        content="web_search: CrewAI excels at role-based tasks, LangGraph at complex state management",
    )
    time.sleep(1)

    pp.agent_completed(
        "senior-researcher",
        output="Comprehensive comparison: CrewAI (role-based, simple setup), "
        "LangGraph (stateful graphs, flexible), AutoGen (event-driven, scalable), "
        "OpenAI SDK (native integration, minimal overhead)",
    )
    pp.stage_exited("research", run_id=run_id)
    time.sleep(1.5)

    # -- Stage 2: Content Writing --
    pp.stage_entered("content", run_id=run_id)
    pp.agent_started(
        "content-writer",
        task="Write a 500-word blog post about AI agent frameworks",
    )
    time.sleep(2)

    pp.agent_thinking(
        "content-writer",
        thought="Structuring blog post: intro, framework comparison table, "
        "use case recommendations, conclusion",
    )
    time.sleep(2)

    pp.agent_thinking(
        "content-writer",
        thought="Writing introduction: The AI agent landscape in 2026 has matured "
        "significantly, with four major frameworks competing for developer mindshare...",
    )
    time.sleep(2)

    pp.agent_thinking(
        "content-writer",
        thought="Adding comparison section: Each framework takes a distinct approach "
        "to multi-agent orchestration...",
    )
    pp.cost_update(
        "content-writer",
        cost=0.008,
        tokens_in=3000,
        tokens_out=1200,
        model="gpt-4.1",
    )
    time.sleep(1.5)

    pp.artifact_created(
        "content-writer",
        artifact_type="text",
        content="Blog post draft: 'The AI Agent Framework Landscape in 2026' "
        "- 487 words covering architecture, use cases, and recommendations",
    )
    pp.agent_completed(
        "content-writer",
        output="Blog post: 'The AI Agent Framework Landscape in 2026' (487 words)",
    )
    pp.stage_exited("content", run_id=run_id)
    time.sleep(1.5)

    # -- Stage 3: Review --
    pp.stage_entered("review", run_id=run_id)
    pp.agent_started(
        "quality-reviewer",
        task="Review the blog post for accuracy, clarity, and engagement",
    )
    time.sleep(2)

    pp.agent_thinking(
        "quality-reviewer",
        thought="Checking factual accuracy: verifying framework capabilities and release dates",
    )
    time.sleep(1.5)

    pp.agent_thinking(
        "quality-reviewer",
        thought="Clarity review: the comparison table is effective but the introduction "
        "could be more engaging. Suggesting a real-world example hook.",
    )
    time.sleep(1.5)

    pp.agent_thinking(
        "quality-reviewer",
        thought="Final assessment: content is accurate and well-structured. "
        "Minor suggestion: add a 'when to use each' decision matrix.",
    )
    pp.cost_update(
        "quality-reviewer",
        cost=0.004,
        tokens_in=1500,
        tokens_out=600,
        model="gpt-4.1",
    )
    time.sleep(1)

    pp.agent_completed(
        "quality-reviewer",
        output="Review complete: content approved with minor suggestions. "
        "Score: 8.5/10. Added decision matrix recommendation.",
    )
    pp.stage_exited("review", run_id=run_id)

    total_cost = 0.005 + 0.008 + 0.004
    pp.run_completed(run_id, status="completed", total_cost=total_cost)
    print("\n  Simulation complete! Check the dashboard at http://localhost:8765")


if __name__ == "__main__":
    has_sdk = False
    has_key = bool(os.environ.get("OPENAI_API_KEY"))

    try:
        import crewai  # noqa: F401

        has_sdk = True
    except ImportError:
        pass

    if has_sdk and has_key:
        sim_thread = threading.Thread(target=run_with_real_crewai, daemon=True)
    else:
        if not has_sdk:
            print("  crewai not installed -- running simulation mode")
            print("  Install with: pip install pixelpulse[crewai]")
        elif not has_key:
            print("  OPENAI_API_KEY not set -- running simulation mode")
        sim_thread = threading.Thread(target=run_simulation, daemon=True)

    sim_thread.start()
    pp.serve()
