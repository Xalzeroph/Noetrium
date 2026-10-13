from __future__ import annotations

import pytest
from tests_support import task_for_test
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_payload

from noetrium_platform.research.experimentation.lifecycle.experiment.api import (
    ExperimentWorkloadFailure,
    FailureScope,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    TaskRelation,
    assignment_workload,
    assignment_workload_digest,
    assignment_workload_task_ids,
    assignment_workload_dependencies_for,
    task_graph,
    task_graph_relation,
)


from noetrium_platform.research.experimentation.lifecycle.study.api import (
    assignment_workload_task_index,
)
import noetrium_platform.research.experimentation.lifecycle.study.api.contracts as study_contracts

def _workload(
    task_ids: tuple[str, ...],
    relations=(),
):
    return assignment_workload(task_ids, task_graph(tuple(relations)))



def test_singleton_workload_digest_preserves_task_semantic_identity() -> None:
    left = assignment_workload(("task-a",))
    right = assignment_workload(("task-b",))
    assert assignment_workload_digest(left) != assignment_workload_digest(right)
    assert assignment_workload_task_ids(left) == ("task-a",)
    assert assignment_workload_task_ids(right) == ("task-b",)

def test_task_graph_orders_prerequisites_and_retries() -> None:
    workload = _workload(
        ("child", "retry", "root"),
        (
            task_graph_relation("root", "child", TaskRelation.PREREQUISITE),
            task_graph_relation("root", "retry", TaskRelation.RETRY_OF),
        ),
    )
    order = assignment_workload_task_ids(workload)
    assert order[0] == "root"
    assert set(order[1:]) == {"child", "retry"}


def test_task_graph_rejects_relation_outside_execution_cut() -> None:
    graph = task_graph(
        (
            task_graph_relation(
                "root",
                "child",
                TaskRelation.PREREQUISITE,
            ),
        )
    )
    with pytest.raises(ValueError, match="outside workload"):
        assignment_workload(("child",), graph)


def test_failure_scope_controls_continuation() -> None:
    task_failure = ExperimentWorkloadFailure(
        "decision", "TASK_FAILED", "bad task"
    )
    branch_failure = ExperimentWorkloadFailure(
        "observe",
        "BRANCH_FAILED",
        "state lost",
        scope=FailureScope.BRANCH,
    )
    assert task_failure.may_continue_with_next_task is True
    assert branch_failure.may_continue_with_next_task is False


def test_task_graph_uses_canonical_dependency_order() -> None:
    workload = _workload(
        ("c", "d", "b", "a"),
        (
            task_graph_relation("a", "c", TaskRelation.PREREQUISITE),
            task_graph_relation("b", "c", TaskRelation.PREREQUISITE),
            task_graph_relation("b", "d", TaskRelation.PREREQUISITE),
        ),
    )
    order = assignment_workload_task_ids(workload)
    positions = {task_id: index for index, task_id in enumerate(order)}
    assert set(order) == {"a", "b", "c", "d"}
    assert positions["a"] < positions["c"]
    assert positions["b"] < positions["c"]
    assert positions["b"] < positions["d"]


def test_task_graph_handles_deep_dependency_chains_without_recursion() -> None:
    count = 1500
    relations = tuple(
        task_graph_relation(
            f"task-{index - 1}",
            f"task-{index}",
            TaskRelation.PREREQUISITE,
        )
        for index in range(1, count)
    )
    workload = _workload(
        tuple(f"task-{index}" for index in reversed(range(count))),
        relations,
    )
    ordered = assignment_workload_task_ids(workload)
    assert len(ordered) == count
    assert ordered[0] == "task-0"
    assert ordered[-1] == f"task-{count - 1}"


def test_experiment_task_payload_is_frozen_at_authoring_boundary() -> None:
    payload = {
        "question": "What is 2+2?",
        "tags": ["math"],
    }
    task = task_for_test(
        "payload",
        "qa",
        "solve",
        payload=payload,
    )
    payload["question"] = "mutated"
    payload["tags"].append("changed")
    assert {k: v for k, v in task_payload(task).items() if k != "objective"} == {
        "question": "What is 2+2?",
        "tags": ("math",),
    }


def test_assignment_workload_reuses_compiled_order_and_source_indexes(
    monkeypatch,
) -> None:
    workload = _workload(
        ("child", "retry", "root"),
        (
            task_graph_relation(
                "root",
                "child",
                TaskRelation.PREREQUISITE,
            ),
            task_graph_relation(
                "root",
                "retry",
                TaskRelation.RETRY_OF,
            ),
        ),
    )

    # Materialize both derived indexes once. Sibling order is canonical but
    # intentionally not part of the task-dependency semantics.
    child_index = assignment_workload_task_ids(workload).index("child")
    assert assignment_workload_task_index(workload, "child") == child_index
    assert assignment_workload_dependencies_for(workload, "child") == ("root",)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("immutable workload index was recomputed")

    monkeypatch.setattr(study_contracts, "structure_topological_order", forbidden)
    monkeypatch.setattr(study_contracts, "task_graph_relation_kind", forbidden)

    # Repeated lookups must be served entirely by the content-addressed
    # immutable indexes, with no graph/relation rescan.
    assert assignment_workload_task_index(workload, "child") == child_index
    assert assignment_workload_dependencies_for(workload, "child") == ("root",)



def test_assignment_dependency_lookup_returns_precompiled_tuple_identity() -> None:
    workload = _workload(
        ("a", "b", "c"),
        (
            task_graph_relation("a", "c", TaskRelation.PREREQUISITE),
            task_graph_relation("b", "c", TaskRelation.RETRY_OF),
        ),
    )

    first = assignment_workload_dependencies_for(workload, "c")
    second = assignment_workload_dependencies_for(workload, "c")
    assert set(first) == {"a", "b"}
    assert first is second

    prerequisite = study_contracts.assignment_workload_prerequisites_for(
        workload,
        "c",
    )
    retry = study_contracts.assignment_workload_retry_sources_for(
        workload,
        "c",
    )
    assert prerequisite == ("a",)
    assert retry == ("b",)
    assert prerequisite is study_contracts.assignment_workload_prerequisites_for(
        workload,
        "c",
    )
    assert retry is study_contracts.assignment_workload_retry_sources_for(
        workload,
        "c",
    )
