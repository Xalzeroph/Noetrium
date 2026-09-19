from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTaskSpec,
    ExperimentWorkloadFailure,
    FailureScope,
    validate_task_graph,
)


def test_generic_task_graph_orders_prerequisites_and_retries() -> None:
    ordered = validate_task_graph(
        (
            ExperimentTaskSpec("child", "task", "child", depends_on_task_ids=("root",)),
            ExperimentTaskSpec("retry", "task", "retry", retry_of_task_id="root"),
            ExperimentTaskSpec("root", "task", "root"),
        )
    )

    assert tuple(task.task_id for task in ordered) == ("root", "child", "retry")


def test_generic_task_graph_rejects_an_incomplete_execution_cut() -> None:
    with pytest.raises(ValueError, match="omit prerequisites"):
        validate_task_graph(
            (
                ExperimentTaskSpec("root", "task", "root"),
                ExperimentTaskSpec("child", "task", "child", depends_on_task_ids=("root",)),
            ),
            selected_ids=("child",),
        )


def test_failure_scope_controls_continuation() -> None:
    task_failure = ExperimentWorkloadFailure("decision", "TASK_FAILED", "bad task")
    branch_failure = ExperimentWorkloadFailure(
        "observe", "BRANCH_FAILED", "state lost", scope=FailureScope.BRANCH
    )

    assert task_failure.may_continue_with_next_task is True
    assert branch_failure.may_continue_with_next_task is False


def test_task_graph_preserves_depth_first_dependency_order() -> None:
    ordered = validate_task_graph(
        (
            ExperimentTaskSpec(
                "c", "task", "c", depends_on_task_ids=("a", "b")
            ),
            ExperimentTaskSpec("d", "task", "d", depends_on_task_ids=("b",)),
            ExperimentTaskSpec("b", "task", "b"),
            ExperimentTaskSpec("a", "task", "a"),
        )
    )
    assert tuple(task.task_id for task in ordered) == ("a", "b", "c", "d")


def test_task_graph_handles_deep_dependency_chains_without_recursion() -> None:
    tasks = tuple(
        ExperimentTaskSpec(
            f"task-{index}",
            "task",
            f"task-{index}",
            depends_on_task_ids=((f"task-{index - 1}",) if index else ()),
        )
        for index in reversed(range(1500))
    )
    ordered = validate_task_graph(tasks)
    assert len(ordered) == 1500
    assert ordered[0].task_id == "task-0"
    assert ordered[-1].task_id == "task-1499"
