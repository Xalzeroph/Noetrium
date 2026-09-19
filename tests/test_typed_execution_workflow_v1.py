from noetrium_platform.research.execution.workflow.api import (
    WorkflowGraph,
    WorkflowGraphError,
    WorkflowStep,
)

def test_workflow_graph_is_explicit_and_deterministic():
    graph = WorkflowGraph((
        WorkflowStep("prepare", "effect.prepare"),
        WorkflowStep("left", "work.left", ("prepare",)),
        WorkflowStep("right", "work.right", ("prepare",)),
        WorkflowStep("commit", "effect.commit", ("left", "right")),
    ))
    assert graph.topological_order() == ("prepare", "left", "right", "commit")
    assert graph.ready_steps(frozenset({"prepare"})) == ("left", "right")


def test_workflow_graph_rejects_cycle_and_missing_dependency():
    for steps in (
        (WorkflowStep("a", "a", ("b",)), WorkflowStep("b", "b", ("a",))),
        (WorkflowStep("a", "a", ("missing",)),),
    ):
        try:
            WorkflowGraph(steps)
        except WorkflowGraphError:
            pass
        else:
            raise AssertionError("invalid workflow graph must fail before side effects")


def test_workflow_identity_fields_do_not_coerce_non_text_values():
    try:
        WorkflowStep(1, "work")  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("workflow step identity must remain typed")

    try:
        WorkflowStep("step", "work", dependencies=(1,))  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("workflow dependency identity must remain typed")
