"""Workflow semantic schema over the single NoetriumUnit kernel."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import endpoint_unit, relation_unit, structure_unit


from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    NoetriumUnit,
    NoetriumUnit,
    structure_ready_targets,
    structure_topological_order,
)

WORKFLOW_GRAPH_TRAIT = "workflow.graph"
WORKFLOW_STEP_TRAIT = "workflow.step"
WORKFLOW_DEPENDENCY_RELATION = "workflow.depends-on"


class WorkflowGraphError(ValueError):
    pass


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _tokens(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(row) is not str or not row.strip() for row in value):
        raise TypeError(f"{field} must be a text tuple")
    rows = tuple(row.strip() for row in value)
    if len(rows) != len(set(rows)):
        raise WorkflowGraphError(f"{field} must be unique")
    return rows


def workflow_step(
    step_id: str,
    operation_type: str,
    *,
    required_capabilities: tuple[str, ...] = (),
) -> NoetriumUnit:
    step_id = _text(step_id, "workflow step_id")
    operation_type = _text(operation_type, "workflow operation_type")
    capabilities = _tokens(required_capabilities, "workflow required_capabilities")
    return structure_unit(
        step_id,
        traits=(WORKFLOW_STEP_TRAIT,),
        parameters={
            "operation_type": operation_type,
            "required_capabilities": capabilities,
        },
    )


def workflow_dependency(source_step_id: str, target_step_id: str) -> NoetriumUnit:
    source = _text(source_step_id, "workflow dependency source")
    target = _text(target_step_id, "workflow dependency target")
    if source == target:
        raise WorkflowGraphError("workflow step cannot depend on itself")
    return relation_unit(
        (endpoint_unit(source, None),),
        (endpoint_unit(target, None),),
        WORKFLOW_DEPENDENCY_RELATION,
    )


def workflow_graph(
    steps: tuple[NoetriumUnit, ...],
    dependencies: tuple[NoetriumUnit, ...] = (),
    *,
    graph_id: str = "workflow",
) -> NoetriumUnit:
    if type(steps) is not tuple or any(
        type(step) is not NoetriumUnit or not step.has_trait(WORKFLOW_STEP_TRAIT)
        for step in steps
    ):
        raise TypeError("workflow steps must be workflow.step NoetriumUnit tuple")
    if type(dependencies) is not tuple or any(
        type(row) is not NoetriumUnit for row in dependencies
    ):
        raise TypeError("workflow dependencies must be NoetriumUnit tuple")
    step_ids = {step.unit_id for step in steps}
    for relation in dependencies:
        if relation.relation_id != WORKFLOW_DEPENDENCY_RELATION:
            raise WorkflowGraphError("workflow graph contains unsupported relation")
        source = relation.sources[0].child_id
        target = relation.targets[0].child_id
        if source not in step_ids or target not in step_ids:
            raise WorkflowGraphError("workflow dependency references unknown step")
        if relation.sources[0].port_name is not None or relation.targets[0].port_name is not None:
            raise WorkflowGraphError("workflow dependency cannot bind ports")
    graph = structure_unit(
        _text(graph_id, "workflow graph_id"),
        traits=(WORKFLOW_GRAPH_TRAIT,),
        members=steps,
        relations=dependencies,
    )
    validate_workflow_graph(graph)
    return graph


def validate_workflow_graph(graph: NoetriumUnit) -> None:
    if type(graph) is not NoetriumUnit or not graph.has_trait(WORKFLOW_GRAPH_TRAIT):
        raise TypeError("workflow graph must be workflow.graph NoetriumUnit")
    ids = {step.unit_id for step in graph.members}
    for step in graph.members:
        if not step.has_trait(WORKFLOW_STEP_TRAIT):
            raise TypeError("workflow graph children must have workflow.step trait")
        workflow_step_operation_type(step)
        workflow_step_required_capabilities(step)
    for relation in graph.relations:
        if relation.relation_id != WORKFLOW_DEPENDENCY_RELATION:
            raise WorkflowGraphError("workflow graph contains unsupported relation")
        source = relation.sources[0].child_id
        target = relation.targets[0].child_id
        if source not in ids or target not in ids:
            raise WorkflowGraphError("workflow dependency references unknown step")
        if relation.sources[0].port_name is not None or relation.targets[0].port_name is not None:
            raise WorkflowGraphError("workflow dependency cannot bind ports")
    workflow_topological_order(graph)


def workflow_step_operation_type(step: NoetriumUnit) -> str:
    if type(step) is not NoetriumUnit or not step.has_trait(WORKFLOW_STEP_TRAIT):
        raise TypeError("workflow step must be workflow.step NoetriumUnit")
    return _text(step.parameters.get("operation_type"), "workflow operation_type")


def workflow_step_required_capabilities(step: NoetriumUnit) -> tuple[str, ...]:
    if type(step) is not NoetriumUnit or not step.has_trait(WORKFLOW_STEP_TRAIT):
        raise TypeError("workflow step must be workflow.step NoetriumUnit")
    return _tokens(step.parameters.get("required_capabilities", ()), "workflow required_capabilities")


def workflow_dependencies(graph: NoetriumUnit, step_id: str) -> tuple[str, ...]:
    step_id = _text(step_id, "workflow step_id")
    graph.member(step_id)
    return tuple(sorted(
        relation.sources[0].child_id
        for relation in graph.relations
        if relation.relation_id == WORKFLOW_DEPENDENCY_RELATION
        and relation.targets[0].child_id == step_id
        and relation.sources[0].child_id is not None
    ))


def workflow_topological_order(graph: NoetriumUnit) -> tuple[str, ...]:
    if type(graph) is not NoetriumUnit or not graph.has_trait(WORKFLOW_GRAPH_TRAIT):
        raise TypeError("workflow graph must be workflow.graph NoetriumUnit")
    try:
        return structure_topological_order(graph, (WORKFLOW_DEPENDENCY_RELATION,))
    except ValueError as exc:
        raise WorkflowGraphError(str(exc)) from exc


def workflow_ready_steps(
    graph: NoetriumUnit,
    completed: frozenset[str],
    running: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    if type(graph) is not NoetriumUnit or not graph.has_trait(WORKFLOW_GRAPH_TRAIT):
        raise TypeError("workflow graph must be workflow.graph NoetriumUnit")
    known = frozenset(step.unit_id for step in graph.members)
    unknown = (completed | running) - known
    if unknown:
        raise WorkflowGraphError(
            f"workflow progress references unknown steps: {sorted(unknown)}"
        )
    ready = structure_ready_targets(
        graph,
        satisfied_members=completed,
        relation_ids=frozenset({WORKFLOW_DEPENDENCY_RELATION}),
    )
    return tuple(step_id for step_id in ready if step_id not in running)


__all__ = [
    "WORKFLOW_DEPENDENCY_RELATION",
    "WORKFLOW_GRAPH_TRAIT",
    "WORKFLOW_STEP_TRAIT",
    "WorkflowGraphError",
    "validate_workflow_graph",
    "workflow_dependencies",
    "workflow_dependency",
    "workflow_graph",
    "workflow_ready_steps",
    "workflow_step",
    "workflow_step_operation_type",
    "workflow_step_required_capabilities",
    "workflow_topological_order",
]
