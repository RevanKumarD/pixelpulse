"""AutoGen + PixelPulse example -- multi-agent code review pipeline.

Demonstrates a 3-agent team (coder, reviewer, executor) running inside
AutoGen's RoundRobinGroupChat, fully instrumented with PixelPulse so
every message is visible in the pixel-art dashboard.

This example works in TWO modes:

  1. **With AutoGen installed** (pip install pixelpulse[autogen]):
     Uses real AutoGen agents.  Requires an OpenAI API key in the
     OPENAI_API_KEY environment variable.

  2. **Without AutoGen** (default):
     Falls back to a simulation that emits the same PixelPulse events
     you would see from a real AutoGen run, so you can explore the
     dashboard without any extra dependencies.

Run with:
    python examples/autogen_example.py

Then open http://localhost:8765 in your browser.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from pixelpulse import PixelPulse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 1. Configure PixelPulse with the agents we expect in the team
# --------------------------------------------------------------------------
pp = PixelPulse(
    agents={
        "coder": {
            "team": "engineering",
            "role": "Writes Python code to solve the task",
        },
        "reviewer": {
            "team": "engineering",
            "role": "Reviews code for correctness and style",
        },
        "executor": {
            "team": "ops",
            "role": "Executes code and reports results",
        },
    },
    teams={
        "engineering": {"label": "Engineering", "color": "#00d4ff"},
        "ops": {"label": "Operations", "color": "#ffae00"},
    },
    pipeline=["engineering", "ops"],
    title="AutoGen Code-Review Pipeline",
)


# --------------------------------------------------------------------------
# 2. Try the real AutoGen path; fall back to simulation
# --------------------------------------------------------------------------

def _try_real_autogen() -> bool:
    """Return True if autogen-agentchat is available."""
    try:
        import autogen_agentchat  # noqa: F401
        return True
    except ImportError:
        return False


async def run_real_autogen() -> None:
    """Run a real AutoGen RoundRobinGroupChat instrumented with PixelPulse.

    Requires:
      - pip install pixelpulse[autogen]
      - OPENAI_API_KEY environment variable set
    """
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    model_client = OpenAIChatCompletionClient(model="gpt-4o-mini")

    coder = AssistantAgent(
        name="coder",
        model_client=model_client,
        system_message=(
            "You are a Python developer. Write clean, well-documented code. "
            "When your code has been reviewed and approved, reply TERMINATE."
        ),
    )

    reviewer = AssistantAgent(
        name="reviewer",
        model_client=model_client,
        system_message=(
            "You are a senior code reviewer. Review the code for correctness, "
            "style, and edge cases. If the code is good, say APPROVE. "
            "Otherwise, provide specific feedback for the coder."
        ),
    )

    executor = AssistantAgent(
        name="executor",
        model_client=model_client,
        system_message=(
            "You simulate running the code. Describe what the output would be. "
            "If everything looks correct, say TERMINATE."
        ),
    )

    termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(12)
    team = RoundRobinGroupChat(
        [coder, reviewer, executor],
        termination_condition=termination,
    )

    # 3. Instrument the team with PixelPulse
    adapter = pp.adapter("autogen")
    adapter.instrument(team)

    logger.info("Running real AutoGen team -- check the dashboard at http://localhost:8765")

    # 4. Run the team
    result = await team.run(
        task="Write a Python function that computes the Fibonacci sequence using memoization."
    )

    logger.info("Team finished. Stop reason: %s", getattr(result, "stop_reason", "n/a"))

    # 5. Clean up
    adapter.detach()
    await model_client.close()


# --------------------------------------------------------------------------
# 3. Simulation fallback (no AutoGen needed)
# --------------------------------------------------------------------------

def run_simulation() -> None:
    """Simulate a 3-agent AutoGen conversation using direct PixelPulse events.

    This produces the same dashboard experience as a real AutoGen run,
    letting you explore the UI without installing autogen-agentchat.
    """
    logger.info("AutoGen not installed -- running simulated pipeline")
    logger.info("Dashboard at http://localhost:8765")

    time.sleep(3)  # Let the server and browser start

    # -- Run starts --
    pp.run_started("ag-run-1", name="Fibonacci memoization task")
    pp.stage_entered("engineering", run_id="ag-run-1")

    # -- Coder writes code --
    pp.agent_started("coder", task="Write Fibonacci with memoization")
    time.sleep(2)
    pp.agent_thinking("coder", thought="Using functools.lru_cache for clean memoization")
    time.sleep(1.5)

    code_output = (
        "def fibonacci(n, memo={}):\n"
        "    if n in memo:\n"
        "        return memo[n]\n"
        "    if n <= 1:\n"
        "        return n\n"
        "    memo[n] = fibonacci(n-1, memo) + fibonacci(n-2, memo)\n"
        "    return memo[n]"
    )
    pp.artifact_created("coder", artifact_type="code", content=code_output)
    pp.cost_update("coder", cost=0.003, tokens_in=500, tokens_out=250, model="gpt-4o-mini")
    pp.agent_message("coder", "reviewer", content=code_output[:150], tag="data")
    pp.agent_completed("coder", output="Fibonacci function with memoization via default dict")
    time.sleep(1)

    # -- Reviewer reviews --
    pp.agent_started("reviewer", task="Review Fibonacci implementation")
    time.sleep(2)
    pp.agent_thinking(
        "reviewer",
        thought="Mutable default argument is a known Python gotcha -- suggesting lru_cache instead",
    )
    time.sleep(1)

    feedback = (
        "The mutable default dict is a subtle bug. Use @functools.lru_cache(maxsize=None) "
        "for a cleaner, thread-safe approach. Also add a docstring and type hints."
    )
    pp.agent_message("reviewer", "coder", content=feedback[:200], tag="data")
    pp.cost_update("reviewer", cost=0.002, tokens_in=600, tokens_out=180, model="gpt-4o-mini")
    pp.agent_completed("reviewer", output=feedback)
    time.sleep(1)

    # -- Coder revises --
    pp.agent_started("coder", task="Revise Fibonacci per reviewer feedback")
    time.sleep(2)
    pp.agent_thinking("coder", thought="Switching to functools.lru_cache, adding type hints")
    time.sleep(1)

    revised_code = (
        "import functools\n\n"
        "@functools.lru_cache(maxsize=None)\n"
        "def fibonacci(n: int) -> int:\n"
        '    """Return the n-th Fibonacci number (0-indexed)."""\n'
        "    if n <= 1:\n"
        "        return n\n"
        "    return fibonacci(n - 1) + fibonacci(n - 2)"
    )
    pp.artifact_created("coder", artifact_type="code", content=revised_code)
    pp.cost_update("coder", cost=0.002, tokens_in=400, tokens_out=200, model="gpt-4o-mini")
    pp.agent_message("coder", "reviewer", content="Revised: using lru_cache, added docstring + types", tag="data")
    pp.agent_completed("coder", output="Revised implementation with lru_cache")
    time.sleep(1)

    # -- Reviewer approves --
    pp.agent_started("reviewer", task="Re-review revised Fibonacci")
    time.sleep(1.5)
    pp.agent_thinking("reviewer", thought="lru_cache is correct, type hints present, docstring clear")
    pp.agent_message("reviewer", "executor", content="APPROVE -- code is clean and correct", tag="control")
    pp.cost_update("reviewer", cost=0.001, tokens_in=300, tokens_out=80, model="gpt-4o-mini")
    pp.agent_completed("reviewer", output="APPROVE")
    pp.stage_exited("engineering", run_id="ag-run-1")
    time.sleep(1)

    # -- Executor runs the code --
    pp.stage_entered("ops", run_id="ag-run-1")
    pp.agent_started("executor", task="Execute Fibonacci function")
    time.sleep(2)
    pp.agent_thinking("executor", thought="Running fibonacci(10) => 55, fibonacci(30) => 832040")
    time.sleep(1)

    exec_output = "fibonacci(10) = 55\nfibonacci(30) = 832040\nAll assertions passed."
    pp.artifact_created("executor", artifact_type="text", content=exec_output)
    pp.cost_update("executor", cost=0.001, tokens_in=200, tokens_out=100, model="gpt-4o-mini")
    pp.agent_completed("executor", output="Execution successful. TERMINATE")
    pp.stage_exited("ops", run_id="ag-run-1")

    # -- Run completes --
    total_cost = 0.003 + 0.002 + 0.002 + 0.001 + 0.001
    pp.run_completed("ag-run-1", status="completed", total_cost=total_cost)

    logger.info("Simulation complete! Check the dashboard.")


# --------------------------------------------------------------------------
# 4. Main entry point
# --------------------------------------------------------------------------

def main() -> None:
    has_autogen = _try_real_autogen()

    if has_autogen:
        # Run real AutoGen in a background thread
        def _run():
            time.sleep(3)  # Let server start
            asyncio.run(run_real_autogen())

        bg = threading.Thread(target=_run, daemon=True)
        bg.start()
    else:
        # Run simulation in a background thread
        bg = threading.Thread(target=run_simulation, daemon=True)
        bg.start()

    # Start the PixelPulse dashboard (blocking)
    pp.serve()


if __name__ == "__main__":
    main()
