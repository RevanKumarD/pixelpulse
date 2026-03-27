"""Tests for the A2A-inspired task lifecycle manager."""
from __future__ import annotations

import pytest

from pixelpulse.lifecycle import (
    AgentCard,
    InvalidTransitionError,
    Task,
    TaskManager,
    TaskState,
)


class TestTaskState:
    """Test TaskState enum values."""

    def test_all_states_exist(self):
        states = {s.value for s in TaskState}
        assert states == {
            "submitted", "working", "input_required",
            "completed", "failed", "canceled",
        }


class TestAgentCard:
    """Test AgentCard creation and serialization."""

    def test_from_dict(self):
        card = AgentCard.from_dict({
            "agent_id": "researcher",
            "name": "Research Agent",
            "description": "Finds information",
            "skills": ["search", "summarize"],
        })
        assert card.agent_id == "researcher"
        assert card.name == "Research Agent"
        assert card.skills == ("search", "summarize")
        assert card.accepts_input is True

    def test_to_dict_round_trip(self):
        original = AgentCard(
            agent_id="writer",
            name="Writer",
            description="Writes content",
            skills=("write", "edit"),
        )
        data = original.to_dict()
        restored = AgentCard.from_dict(data)
        assert restored.agent_id == original.agent_id
        assert restored.name == original.name
        assert restored.skills == original.skills

    def test_from_dict_with_id_fallback(self):
        card = AgentCard.from_dict({"id": "fallback_agent"})
        assert card.agent_id == "fallback_agent"


class TestTaskImmutability:
    """Test that Task objects are immutable."""

    def test_with_state_returns_new_task(self):
        task = Task(
            task_id="t1",
            state=TaskState.SUBMITTED,
            agent_id="agent1",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        new_task = task.with_state(TaskState.WORKING)

        assert task.state == TaskState.SUBMITTED
        assert new_task.state == TaskState.WORKING
        assert new_task.task_id == task.task_id
        assert len(new_task.history) == len(task.history) + 1

    def test_with_state_preserves_data(self):
        task = Task(
            task_id="t2",
            state=TaskState.WORKING,
            agent_id="agent2",
            input_data={"query": "test"},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        completed = task.with_state(
            TaskState.COMPLETED,
            output_data={"result": "done"},
        )
        assert completed.input_data == {"query": "test"}
        assert completed.output_data == {"result": "done"}


class TestTaskManager:
    """Test TaskManager lifecycle operations."""

    def setup_method(self):
        self.tm = TaskManager(pp=None)

    def test_submit_creates_task(self):
        task = self.tm.submit("researcher", input_data={"query": "trends"})

        assert task.state == TaskState.SUBMITTED
        assert task.agent_id == "researcher"
        assert task.input_data == {"query": "trends"}
        assert task.task_id in self.tm.tasks

    def test_submit_with_custom_id(self):
        task = self.tm.submit("writer", task_id="custom-123")
        assert task.task_id == "custom-123"

    def test_valid_transition_submitted_to_working(self):
        task = self.tm.submit("agent1")
        updated = self.tm.transition(task.task_id, TaskState.WORKING)

        assert updated.state == TaskState.WORKING
        assert len(updated.history) == 2

    def test_valid_transition_working_to_completed(self):
        task = self.tm.submit("agent1")
        self.tm.transition(task.task_id, TaskState.WORKING)
        completed = self.tm.transition(
            task.task_id,
            TaskState.COMPLETED,
            output_data={"result": "all done"},
        )

        assert completed.state == TaskState.COMPLETED
        assert completed.output_data == {"result": "all done"}

    def test_valid_transition_working_to_failed(self):
        task = self.tm.submit("agent1")
        self.tm.transition(task.task_id, TaskState.WORKING)
        failed = self.tm.transition(
            task.task_id,
            TaskState.FAILED,
            error="Something broke",
        )

        assert failed.state == TaskState.FAILED
        assert failed.error == "Something broke"

    def test_valid_transition_working_to_input_required(self):
        task = self.tm.submit("agent1")
        self.tm.transition(task.task_id, TaskState.WORKING)
        paused = self.tm.transition(task.task_id, TaskState.INPUT_REQUIRED)

        assert paused.state == TaskState.INPUT_REQUIRED

    def test_valid_transition_input_required_to_working(self):
        task = self.tm.submit("agent1")
        self.tm.transition(task.task_id, TaskState.WORKING)
        self.tm.transition(task.task_id, TaskState.INPUT_REQUIRED)
        resumed = self.tm.transition(
            task.task_id,
            TaskState.WORKING,
            input_data={"answer": "42"},
        )

        assert resumed.state == TaskState.WORKING
        assert resumed.input_data == {"answer": "42"}

    def test_invalid_transition_raises(self):
        task = self.tm.submit("agent1")

        with pytest.raises(InvalidTransitionError, match="submitted.*completed"):
            self.tm.transition(task.task_id, TaskState.COMPLETED)

    def test_terminal_state_blocks_transitions(self):
        task = self.tm.submit("agent1")
        self.tm.transition(task.task_id, TaskState.WORKING)
        self.tm.transition(task.task_id, TaskState.COMPLETED)

        with pytest.raises(InvalidTransitionError, match="terminal"):
            self.tm.transition(task.task_id, TaskState.WORKING)

    def test_unknown_task_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown task"):
            self.tm.transition("nonexistent", TaskState.WORKING)

    def test_cancel_from_submitted(self):
        task = self.tm.submit("agent1")
        canceled = self.tm.transition(task.task_id, TaskState.CANCELED)
        assert canceled.state == TaskState.CANCELED

    def test_cancel_from_working(self):
        task = self.tm.submit("agent1")
        self.tm.transition(task.task_id, TaskState.WORKING)
        canceled = self.tm.transition(task.task_id, TaskState.CANCELED)
        assert canceled.state == TaskState.CANCELED

    def test_get_tasks_by_state(self):
        self.tm.submit("a1", task_id="t1")
        self.tm.submit("a2", task_id="t2")
        self.tm.submit("a3", task_id="t3")
        self.tm.transition("t1", TaskState.WORKING)

        submitted = self.tm.get_tasks_by_state(TaskState.SUBMITTED)
        working = self.tm.get_tasks_by_state(TaskState.WORKING)

        assert len(submitted) == 2
        assert len(working) == 1

    def test_get_tasks_by_agent(self):
        self.tm.submit("agent_a", task_id="t1")
        self.tm.submit("agent_a", task_id="t2")
        self.tm.submit("agent_b", task_id="t3")

        tasks = self.tm.get_tasks_by_agent("agent_a")
        assert len(tasks) == 2

    def test_get_task_returns_none_for_missing(self):
        assert self.tm.get_task("nope") is None


class TestAgentCardRegistry:
    """Test agent card registration and discovery."""

    def setup_method(self):
        self.tm = TaskManager(pp=None)

    def test_register_and_lookup(self):
        card = AgentCard(agent_id="r1", name="Researcher", skills=("search",))
        self.tm.register_agent(card)

        found = self.tm.get_agent("r1")
        assert found is not None
        assert found.name == "Researcher"

    def test_register_from_dict(self):
        self.tm.register_agent({
            "agent_id": "w1",
            "name": "Writer",
            "skills": ["write", "edit"],
        })
        found = self.tm.get_agent("w1")
        assert found is not None
        assert found.skills == ("write", "edit")

    def test_unregister(self):
        self.tm.register_agent(AgentCard(agent_id="tmp"))
        self.tm.unregister_agent("tmp")
        assert self.tm.get_agent("tmp") is None

    def test_find_agents_by_skill(self):
        self.tm.register_agent(AgentCard(agent_id="a1", skills=("search", "browse")))
        self.tm.register_agent(AgentCard(agent_id="a2", skills=("write",)))
        self.tm.register_agent(AgentCard(agent_id="a3", skills=("search", "index")))

        searchers = self.tm.find_agents("search")
        assert len(searchers) == 2
        ids = {c.agent_id for c in searchers}
        assert ids == {"a1", "a3"}

    def test_find_agents_empty_result(self):
        self.tm.register_agent(AgentCard(agent_id="a1", skills=("write",)))
        assert self.tm.find_agents("fly") == []
