"""A2A-inspired task lifecycle manager for PixelPulse.

Implements a task state machine inspired by Google's Agent-to-Agent (A2A)
protocol. Tasks transition through well-defined states, and each transition
emits PixelPulse pipeline/agent events so the dashboard reflects the
real-time lifecycle of work flowing through a multi-agent system.

States::

    submitted → working → completed
                       ↘ input_required → working (resume)
                       ↘ failed
                       ↘ canceled

Agent cards provide a lightweight discovery mechanism: each agent
registers its capabilities so that orchestrators can route tasks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pixelpulse.protocol import (
    AGENT_COMPLETED,
    AGENT_ERROR,
    AGENT_STARTED,
    PIPELINE_STAGE_ENTERED,
    PIPELINE_STAGE_EXITED,
    RUN_COMPLETED,
    RUN_STARTED,
    create_event,
)

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


# Valid state transitions
_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.SUBMITTED: frozenset({TaskState.WORKING, TaskState.CANCELED}),
    TaskState.WORKING: frozenset({
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.INPUT_REQUIRED,
    }),
    TaskState.INPUT_REQUIRED: frozenset({TaskState.WORKING, TaskState.CANCELED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELED: frozenset(),
}


@dataclass(frozen=True)
class AgentCard:
    """Lightweight agent capability descriptor (A2A-inspired).

    Agent cards let orchestrators discover what each agent can do
    without coupling to implementation details.
    """

    agent_id: str
    name: str = ""
    description: str = ""
    skills: tuple[str, ...] = ()
    accepts_input: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> AgentCard:
        return cls(
            agent_id=data.get("agent_id", data.get("id", "")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            skills=tuple(data.get("skills", ())),
            accepts_input=data.get("accepts_input", True),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name or self.agent_id,
            "description": self.description,
            "skills": list(self.skills),
            "accepts_input": self.accepts_input,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class Task:
    """Immutable snapshot of a task in the A2A lifecycle."""

    task_id: str
    state: TaskState
    agent_id: str
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    history: tuple[tuple[str, str], ...] = ()  # (state, timestamp) pairs

    def with_state(self, new_state: TaskState, **updates: Any) -> Task:
        """Return a new Task with the given state and optional field updates."""
        now = _utc_now()
        new_history = (*self.history, (new_state.value, now))
        base = {
            "task_id": self.task_id,
            "state": new_state,
            "agent_id": self.agent_id,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": now,
            "history": new_history,
        }
        base.update(updates)
        return Task(**base)


class InvalidTransitionError(Exception):
    """Raised when a task state transition is not allowed."""


class TaskManager:
    """Manages A2A-style task lifecycles and emits PixelPulse events.

    Usage::

        from pixelpulse import PixelPulse
        from pixelpulse.lifecycle import TaskManager

        pp = PixelPulse(agents={...}, teams={...})
        tm = TaskManager(pp)

        task = tm.submit("researcher", input_data={"query": "trends"})
        task = tm.transition(task.task_id, TaskState.WORKING)
        task = tm.transition(task.task_id, TaskState.COMPLETED, output_data={"result": "..."})
    """

    def __init__(self, pp: PixelPulse | None = None) -> None:
        self._pp = pp
        self._tasks: dict[str, Task] = {}
        self._agent_cards: dict[str, AgentCard] = {}

    @property
    def tasks(self) -> dict[str, Task]:
        """Read-only view of all tracked tasks."""
        return dict(self._tasks)

    @property
    def agent_cards(self) -> dict[str, AgentCard]:
        """Read-only view of registered agent cards."""
        return dict(self._agent_cards)

    # ---- Agent Card Registry ----

    def register_agent(self, card: AgentCard | dict) -> AgentCard:
        """Register an agent card for capability discovery."""
        if isinstance(card, dict):
            card = AgentCard.from_dict(card)
        self._agent_cards = {**self._agent_cards, card.agent_id: card}
        return card

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent card."""
        self._agent_cards = {
            k: v for k, v in self._agent_cards.items() if k != agent_id
        }

    def get_agent(self, agent_id: str) -> AgentCard | None:
        """Look up an agent card by ID."""
        return self._agent_cards.get(agent_id)

    def find_agents(self, skill: str) -> list[AgentCard]:
        """Find agents that have a specific skill."""
        return [
            card for card in self._agent_cards.values()
            if skill in card.skills
        ]

    # ---- Task Lifecycle ----

    def submit(
        self,
        agent_id: str,
        input_data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> Task:
        """Create and submit a new task to an agent.

        Emits ``run.started`` and ``pipeline.stage_entered`` events.
        """
        now = _utc_now()
        tid = task_id or f"task_{uuid4().hex[:12]}"
        task = Task(
            task_id=tid,
            state=TaskState.SUBMITTED,
            agent_id=agent_id,
            input_data=input_data or {},
            created_at=now,
            updated_at=now,
            history=((TaskState.SUBMITTED.value, now),),
        )
        self._tasks = {**self._tasks, tid: task}

        self._emit(create_event(
            RUN_STARTED,
            {"run_id": tid, "name": f"Task for {agent_id}"},
            run_id=tid,
            source_framework="a2a",
        ))
        self._emit(create_event(
            PIPELINE_STAGE_ENTERED,
            {"stage": "submitted", "run_id": tid, "agent_id": agent_id},
            run_id=tid,
            source_framework="a2a",
        ))

        return task

    def transition(
        self,
        task_id: str,
        new_state: TaskState,
        output_data: dict[str, Any] | None = None,
        error: str = "",
        input_data: dict[str, Any] | None = None,
    ) -> Task:
        """Transition a task to a new state with validation.

        Raises :class:`InvalidTransitionError` if the transition is not allowed.
        Emits appropriate PixelPulse events for each transition.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Unknown task: {task_id}")

        allowed = _TRANSITIONS.get(task.state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {task.state.value} to {new_state.value}. "
                f"Allowed: {', '.join(s.value for s in allowed) or 'none (terminal state)'}"
            )

        updates: dict[str, Any] = {}
        if output_data is not None:
            updates["output_data"] = output_data
        if error:
            updates["error"] = error
        if input_data is not None:
            updates["input_data"] = input_data

        new_task = task.with_state(new_state, **updates)
        self._tasks = {**self._tasks, task_id: new_task}

        # Emit events based on the new state
        self._emit_transition_events(task, new_task)

        return new_task

    def get_task(self, task_id: str) -> Task | None:
        """Look up a task by ID."""
        return self._tasks.get(task_id)

    def get_tasks_by_state(self, state: TaskState) -> list[Task]:
        """Get all tasks in a given state."""
        return [t for t in self._tasks.values() if t.state == state]

    def get_tasks_by_agent(self, agent_id: str) -> list[Task]:
        """Get all tasks assigned to an agent."""
        return [t for t in self._tasks.values() if t.agent_id == agent_id]

    # ---- Internal ----

    def _emit(self, event: dict) -> None:
        """Emit a PixelPulse event if a PixelPulse instance is attached."""
        if self._pp is not None:
            self._pp.emit(event)

    def _emit_transition_events(self, old_task: Task, new_task: Task) -> None:
        """Emit PixelPulse events for a state transition."""
        tid = new_task.task_id
        agent = new_task.agent_id
        old_state = old_task.state.value
        new_state = new_task.state.value

        # Exit the old stage
        self._emit(create_event(
            PIPELINE_STAGE_EXITED,
            {"stage": old_state, "run_id": tid, "agent_id": agent},
            run_id=tid,
            source_framework="a2a",
        ))

        # Enter the new stage
        self._emit(create_event(
            PIPELINE_STAGE_ENTERED,
            {"stage": new_state, "run_id": tid, "agent_id": agent},
            run_id=tid,
            source_framework="a2a",
        ))

        # State-specific events
        if new_task.state == TaskState.WORKING:
            self._emit(create_event(
                AGENT_STARTED,
                {"agent_id": agent, "task": f"Working on task {tid}"},
                run_id=tid,
                source_framework="a2a",
            ))

        elif new_task.state == TaskState.COMPLETED:
            self._emit(create_event(
                AGENT_COMPLETED,
                {"agent_id": agent, "output": str(new_task.output_data)[:200]},
                run_id=tid,
                source_framework="a2a",
            ))
            self._emit(create_event(
                RUN_COMPLETED,
                {"run_id": tid, "status": "completed"},
                run_id=tid,
                source_framework="a2a",
            ))

        elif new_task.state == TaskState.FAILED:
            self._emit(create_event(
                AGENT_ERROR,
                {"agent_id": agent, "error": new_task.error or "Task failed"},
                run_id=tid,
                source_framework="a2a",
            ))
            self._emit(create_event(
                RUN_COMPLETED,
                {"run_id": tid, "status": "failed"},
                run_id=tid,
                source_framework="a2a",
            ))

        elif new_task.state == TaskState.CANCELED:
            self._emit(create_event(
                RUN_COMPLETED,
                {"run_id": tid, "status": "canceled"},
                run_id=tid,
                source_framework="a2a",
            ))

        elif new_task.state == TaskState.INPUT_REQUIRED:
            self._emit(create_event(
                AGENT_COMPLETED,
                {
                    "agent_id": agent,
                    "output": "Awaiting additional input",
                    "input_required": True,
                },
                run_id=tid,
                source_framework="a2a",
            ))


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
