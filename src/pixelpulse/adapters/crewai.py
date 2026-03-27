"""CrewAI adapter — hooks into CrewAI's event listener system.

CrewAI provides an event listener API that fires events during crew
execution. This adapter translates those events into PixelPulse events.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)


class CrewAIAdapter:
    """Adapter for CrewAI agent framework.

    Usage::

        from crewai import Crew
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("crewai")
        adapter.instrument(my_crew)

        # Now run the crew — events will flow to the dashboard
        my_crew.kickoff()
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._original_callbacks: dict[str, Any] = {}
        self._crew = None

    def instrument(self, crew: Any) -> None:
        """Attach to a CrewAI Crew instance.

        Hooks into the crew's execution callbacks to capture:
        - Agent task start/complete
        - Agent thinking steps
        - Task delegation (agent-to-agent messages)
        """
        self._crew = crew

        try:
            from crewai import Crew
        except ImportError:
            logger.error(
                "crewai package not installed. Install with: pip install pixelpulse[crewai]"
            )
            return

        # Hook into CrewAI's step callback
        if hasattr(crew, 'step_callback'):
            self._original_callbacks['step'] = crew.step_callback
            crew.step_callback = self._on_step

        # Hook into task callback
        if hasattr(crew, 'task_callback'):
            self._original_callbacks['task'] = crew.task_callback
            crew.task_callback = self._on_task_complete

        logger.info("CrewAI adapter instrumented crew with %d agents", len(getattr(crew, 'agents', [])))

    def detach(self) -> None:
        """Remove instrumentation from the crew."""
        if self._crew is None:
            return
        if 'step' in self._original_callbacks:
            self._crew.step_callback = self._original_callbacks['step']
        if 'task' in self._original_callbacks:
            self._crew.task_callback = self._original_callbacks['task']
        self._original_callbacks.clear()
        self._crew = None

    def _on_step(self, step_output: Any) -> None:
        """Called on each agent step (thinking, tool use, etc.)."""
        agent_name = self._extract_agent_name(step_output)

        if hasattr(step_output, 'thought') and step_output.thought:
            self._pp.agent_thinking(agent_name, thought=str(step_output.thought))
        elif hasattr(step_output, 'tool') and step_output.tool:
            self._pp.agent_thinking(
                agent_name,
                thought=f"Using tool: {step_output.tool}",
            )

        # Chain to original callback
        original = self._original_callbacks.get('step')
        if original:
            original(step_output)

    def _on_task_complete(self, task_output: Any) -> None:
        """Called when a task completes."""
        agent_name = self._extract_agent_name(task_output)
        output_text = str(getattr(task_output, 'raw', task_output))

        self._pp.agent_completed(agent_name, output=output_text)

        # Chain to original callback
        original = self._original_callbacks.get('task')
        if original:
            original(task_output)

    @staticmethod
    def _extract_agent_name(output: Any) -> str:
        """Extract a usable agent name from a CrewAI output object."""
        if hasattr(output, 'agent') and output.agent:
            agent = output.agent
            if hasattr(agent, 'role'):
                return str(agent.role).lower().replace(" ", "-")
            return str(agent)
        return "unknown-agent"
