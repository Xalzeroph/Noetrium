import pytest
from noetrium_platform.research.execution.workflow.api import (
    WorkflowGraphError, workflow_dependency, workflow_graph, workflow_ready_steps,
    workflow_step, workflow_topological_order,
)


def test_workflow_topology_and_ready_frontier():
    graph = workflow_graph(
        (workflow_step("prepare", "effect.prepare"), workflow_step("left", "work.left"),
         workflow_step("right", "work.right"), workflow_step("commit", "effect.commit")),
        (workflow_dependency("prepare", "left"), workflow_dependency("prepare", "right"),
         workflow_dependency("left", "commit"), workflow_dependency("right", "commit")),
    )
    assert workflow_topological_order(graph) == ("prepare", "left", "right", "commit")
    assert workflow_ready_steps(graph, frozenset()) == ("prepare",)
    assert workflow_ready_steps(graph, frozenset({"prepare"})) == ("left", "right")


@pytest.mark.parametrize("deps", [
    (("a", "b"), ("b", "a")),
    (("missing", "a"),),
])
def test_workflow_rejects_invalid_dependencies(deps):
    steps=(workflow_step("a", "a"), workflow_step("b", "b"))
    relations=tuple(workflow_dependency(a,b) for a,b in deps)
    with pytest.raises(WorkflowGraphError):
        workflow_graph(steps, relations)


def test_workflow_step_rejects_invalid_values():
    with pytest.raises((TypeError, ValueError)):
        workflow_step(1, "work")  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        workflow_step("step", "work", required_capabilities=(1,))  # type: ignore[arg-type]
