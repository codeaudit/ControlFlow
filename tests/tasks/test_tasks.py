from typing import Annotated

import pytest
from pydantic import BaseModel

import controlflow
from controlflow.agents import Agent
from controlflow.flows import Flow
from controlflow.instructions import instructions
from controlflow.tasks.task import (
    COMPLETE_STATUSES,
    INCOMPLETE_STATUSES,
    Task,
    TaskStatus,
)
from controlflow.utilities.context import ctx
from controlflow.utilities.testing import SimpleTask


def test_status_coverage():
    assert INCOMPLETE_STATUSES | COMPLETE_STATUSES == set(TaskStatus)


def test_context_open_and_close():
    assert ctx.get("tasks") == []
    with SimpleTask() as ta:
        assert ctx.get("tasks") == [ta]
        with SimpleTask() as tb:
            assert ctx.get("tasks") == [ta, tb]
        assert ctx.get("tasks") == [ta]
    assert ctx.get("tasks") == []


def test_task_requires_objective():
    with pytest.raises(ValueError):
        Task()


def test_task_initialization():
    task = Task(objective="Test objective")
    assert task.objective == "Test objective"
    assert task.status == TaskStatus.PENDING
    assert task.result is None


def test_stable_id():
    t1 = Task(objective="Test Objective")
    t2 = Task(objective="Test Objective")
    t3 = Task(objective="Test Objective+")
    assert t1.id == t2.id == "9663272a"  # Update this line with the new ID
    assert t3.id != t1.id  # Ensure different objectives produce different IDs


def test_task_mark_successful_and_mark_failed():
    task = Task(objective="Test Objective", result_type=int)
    task.mark_successful(result=5)
    assert task.result == 5
    assert task.status == TaskStatus.SUCCESSFUL
    task.mark_failed(reason="test error")
    assert task.status == TaskStatus.FAILED
    assert task.result == "test error"


def test_task_loads_instructions_at_creation():
    with instructions("test instruction"):
        task = SimpleTask()

    assert "test instruction" in task.instructions


def test_task_dependencies():
    task1 = SimpleTask()
    task2 = SimpleTask(depends_on=[task1])
    assert task1 in task2.depends_on
    assert task2 in task1._downstreams


def test_task_context_dependencies():
    task1 = SimpleTask()
    task2 = SimpleTask(context=dict(a=task1))
    assert task1 in task2.depends_on
    assert task2 in task1._downstreams


def test_task_context_complex_dependencies():
    task1 = SimpleTask()
    task2 = SimpleTask()
    task3 = SimpleTask(context=dict(a=[task1], b=dict(c=[task2])))
    assert task1 in task3.depends_on
    assert task2 in task3.depends_on
    assert task3 in task1._downstreams
    assert task3 in task2._downstreams


def test_task_subtasks():
    task1 = SimpleTask()
    task2 = SimpleTask(parent=task1)
    assert task2 in task1._subtasks
    assert task2.parent is task1


def test_task_parent_context():
    with SimpleTask() as task1:
        with SimpleTask() as task2:
            task3 = SimpleTask()

    assert task3.parent is task2
    assert task2.parent is task1
    assert task1.parent is None

    assert task1._subtasks == {task2}
    assert task2._subtasks == {task3}
    assert task3._subtasks == set()


def test_task_agent_assignment():
    agent = Agent(name="Test Agent")
    task = SimpleTask(agents=[agent])
    assert task.agents == [agent]
    assert task.get_agents() == [agent]


def test_task_bad_agent_assignment():
    with pytest.raises(ValueError):
        SimpleTask(agents=5)


def test_task_loads_agent_from_parent():
    agent = Agent(name="Test Agent")
    with SimpleTask(agents=[agent]):
        child = SimpleTask()

    assert child.agents == []
    assert child.get_agents() == [agent]


def test_task_loads_agent_from_flow():
    def_agent = controlflow.defaults.agent
    agent = Agent(name="Test Agent")
    with Flow(agent=agent):
        task = SimpleTask()

        assert task.agents == []
        assert task.get_agents() == [agent]

    # outside the flow context, pick up the default agent
    assert task.get_agents() == [def_agent]


def test_task_loads_agent_from_default_if_none_otherwise():
    agent = controlflow.defaults.agent
    task = SimpleTask()

    assert task.agents == []
    assert task.get_agents() == [agent]


def test_task_loads_agent_from_parent_before_flow():
    agent1 = Agent(name="Test Agent 1")
    agent2 = Agent(name="Test Agent 2")
    with Flow(agent=agent1):
        with SimpleTask(agents=[agent2]):
            child = SimpleTask()

    assert child.agents == []
    assert child.get_agents() == [agent2]


class TestTaskStatus:
    def test_task_status_transitions(self):
        task = SimpleTask()
        assert task.is_incomplete()
        assert not task.is_running()
        assert not task.is_complete()
        assert not task.is_successful()
        assert not task.is_failed()
        assert not task.is_skipped()

        task.mark_successful()
        assert not task.is_incomplete()
        assert not task.is_running()
        assert task.is_complete()
        assert task.is_successful()
        assert not task.is_failed()
        assert not task.is_skipped()

        task = SimpleTask()
        task.mark_failed()
        assert not task.is_incomplete()
        assert task.is_complete()
        assert not task.is_successful()
        assert task.is_failed()
        assert not task.is_skipped()

        task = SimpleTask()
        task.mark_skipped()
        assert not task.is_incomplete()
        assert task.is_complete()
        assert not task.is_successful()
        assert not task.is_failed()
        assert task.is_skipped()

    def test_validate_upstream_dependencies_on_success(self):
        task1 = SimpleTask()
        task2 = SimpleTask(depends_on=[task1])
        with pytest.raises(ValueError, match="cannot be marked successful"):
            task2.mark_successful()
        task1.mark_successful()
        task2.mark_successful()

    def test_validate_subtask_dependencies_on_success(self):
        task1 = SimpleTask()
        task2 = SimpleTask(parent=task1)
        with pytest.raises(ValueError, match="cannot be marked successful"):
            task1.mark_successful()
        task2.mark_successful()
        task1.mark_successful()

    def test_task_ready(self):
        task1 = SimpleTask()
        assert task1.is_ready()

    def test_task_not_ready_if_successful(self):
        task1 = SimpleTask()
        task1.mark_successful()
        assert not task1.is_ready()

    def test_task_not_ready_if_failed(self):
        task1 = SimpleTask()
        task1.mark_failed()
        assert not task1.is_ready()

    def test_task_not_ready_if_dependencies_are_ready(self):
        task1 = SimpleTask()
        task2 = SimpleTask(depends_on=[task1])
        assert task1.is_ready()
        assert not task2.is_ready()

    def test_task_ready_if_dependencies_are_ready(self):
        task1 = SimpleTask()
        task2 = SimpleTask(depends_on=[task1])
        task1.mark_successful()
        assert not task1.is_ready()
        assert task2.is_ready()

    def test_task_hash(self):
        task1 = SimpleTask()
        task2 = SimpleTask()
        assert hash(task1) != hash(task2)


class TestTaskPrompt:
    def test_default_prompt(self):
        task = SimpleTask()
        assert task.prompt is None

    def test_default_template(self):
        task = SimpleTask()
        prompt = task.get_prompt()
        assert prompt.startswith("- id:")
        assert "- objective: test" in prompt
        assert "- context:" in prompt

    def test_custom_prompt(self):
        task = SimpleTask(prompt="Custom Prompt")
        prompt = task.get_prompt()
        assert prompt == "Custom Prompt"

    def test_custom_templated_prompt(self):
        task = SimpleTask(prompt="{{ task.objective }}", objective="abc")
        prompt = task.get_prompt()
        assert prompt == "abc"


class TestResultType:
    def test_int_result(self):
        task = Task("choose 5", result_type=int)
        task.mark_successful(result=5)
        assert task.result == 5

    def test_str_result(self):
        task = Task("choose 5", result_type=str)
        task.mark_successful(result="5")
        assert task.result == "5"

    def test_tuple_of_ints_result(self):
        task = Task("choose 5", result_type=(4, 5, 6))
        task.mark_successful(result=5)
        assert task.result == 5

    def test_tuple_of_ints_validates(self):
        task = Task("choose 5", result_type=(4, 5, 6))
        with pytest.raises(ValueError):
            task.mark_successful(result=7)

    def test_pydantic_result(self):
        class Name(BaseModel):
            first: str
            last: str

        task = Task("The character said his name is John Doe", result_type=Name)
        task.run()
        assert task.result == Name(first="John", last="Doe")

    def test_annotated_result(self):
        task = Task(
            "complete the task", result_type=Annotated[str, "a 5 digit zip code"]
        )
        task.run()
        assert len(task.result) == 5
        assert int(task.result)


class TestSuccessTool:
    def test_success_tool(self):
        task = Task("choose 5", result_type=int)
        tool = task.create_success_tool()
        tool.run(input=dict(result=5))
        assert task.is_successful()
        assert task.result == 5

    def test_success_tool_with_list_of_options(self):
        task = Task('choose "good"', result_type=["bad", "good", "medium"])
        tool = task.create_success_tool()
        tool.run(input=dict(result=1))
        assert task.is_successful()
        assert task.result == "good"

    def test_success_tool_with_list_of_options_requires_int(self):
        task = Task('choose "good"', result_type=["bad", "good", "medium"])
        tool = task.create_success_tool()
        with pytest.raises(ValueError):
            tool.run(input=dict(result="good"))


@pytest.mark.parametrize(
    "max_turns, max_calls_per_turn, expected_calls",
    [
        (1, 1, 1),
        (1, 2, 2),
        (2, 1, 2),
        (3, 2, 6),
    ],
)
def test_run_with_limits(
    monkeypatch, default_fake_llm, max_turns, max_calls_per_turn, expected_calls
):
    # Tests that the run function correctly limits the number of turns and calls per turn
    default_fake_llm.set_responses(["hello", "world", "how", "are", "you"])

    call_count = 0
    original_run_model = Agent._run_model

    def mock_run_model(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_run_model(*args, **kwargs)

    monkeypatch.setattr(Agent, "_run_model", mock_run_model)

    task = Task("send messages")
    task.run(
        max_calls_per_turn=max_calls_per_turn,
        max_turns=max_turns,
    )

    assert call_count == expected_calls
