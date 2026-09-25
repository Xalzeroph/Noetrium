from __future__ import annotations

import pytest

from noetrium_platform.research.execution.workflow.api import (
    AgentMethodSpec,
    AgentPhaseSpec,
)


def test_agent_method_spec_compiles_sequence_and_cycle() -> None:
    phases = (
        AgentPhaseSpec("observe", "agent.observe", "Observe."),
        AgentPhaseSpec("act", "agent.act", "Act."),
    )
    sequential = AgentMethodSpec(method_id="demo-sequence", phases=phases)
    cyclic = AgentMethodSpec(
        method_id="demo-cycle",
        phases=phases,
        max_cycles=3,
        metric_names=("task_success",),
        artifact_kinds=("trajectory",),
    )
    assert sequential.cyclic is False
    assert cyclic.cyclic is True
    assert sequential.compile().program_identity.implementation.method_id == "demo-sequence"
    assert cyclic.compile().program_identity.implementation.method_id == "demo-cycle"


def test_agent_method_spec_freezes_configuration() -> None:
    mutable = {"nested": ["a", "b"]}
    spec = AgentMethodSpec(
        method_id="freeze-demo",
        phases=(AgentPhaseSpec("act", "agent.act", "Act."),),
        configuration=mutable,
    )
    mutable["nested"].append("c")
    assert tuple(spec.configuration["nested"]) == ("a", "b")


def test_agent_method_spec_rejects_duplicate_surfaces() -> None:
    phase = AgentPhaseSpec("act", "agent.act", "Act.")
    with pytest.raises(ValueError, match="unique"):
        AgentMethodSpec(
            method_id="bad-metrics",
            phases=(phase,),
            metric_names=("score", "score"),
        )
    with pytest.raises(ValueError, match="positive"):
        AgentMethodSpec(
            method_id="bad-cycle",
            phases=(phase,),
            max_cycles=0,
        )


def test_method_workflow_covers_full_graph_without_identity_boilerplate() -> None:
    from noetrium_platform.foundation.kernel.kernel import EffectClass
    from noetrium_platform.research.execution.workflow.api import (
        MethodNodeKind,
        MethodNodeResult,
        MethodRuntimePort,
        MethodWorkflow,
        analyze_method_runtime_requirements,
    )

    def choose(request):
        return MethodNodeResult(
            value=request.previous_value,
            next_node="checkpoint",
        )

    program = (
        MethodWorkflow(
            "workflow-demo",
            configuration={"paper": "demo"},
            metric_names=("success",),
        )
        .agent(
            "observe",
            "agent.observe",
            instruction="Observe the task.",
            next="tool",
            output_schema="observation.v1",
        )
        .capability(
            "tool",
            "environment.act",
            next="decide",
            effect_class=EffectClass.RECONCILABLE,
        )
        .route("decide", choose, ("checkpoint", "interrupt"))
        .checkpoint("checkpoint", next="finish")
        .interrupt("interrupt", next="finish")
        .return_("finish")
        .requires_runtime(MethodRuntimePort.CHILD_MACHINES)
        .build()
    )

    assert program.program_identity.implementation.method_id == "workflow-demo"
    assert program.graph.entrypoint == "observe"
    assert tuple(node.kind for node in program.graph.nodes) == (
        MethodNodeKind.AGENT,
        MethodNodeKind.CAPABILITY,
        MethodNodeKind.ROUTE,
        MethodNodeKind.CHECKPOINT,
        MethodNodeKind.INTERRUPT,
        MethodNodeKind.RETURN,
    )
    requirements = analyze_method_runtime_requirements(program)
    assert requirements.agent_ids == ("agent.observe",)
    assert requirements.capability_ids == ("environment.act",)
    assert requirements.ports == (
        MethodRuntimePort.AGENT_LOOP,
        MethodRuntimePort.CAPABILITIES,
        MethodRuntimePort.CHILD_MACHINES,
        MethodRuntimePort.SCHEMAS,
    )
    assert program.configuration["authoring_form"] == "method_workflow.v1"
    assert program.configuration["paper"] == "demo"


def test_method_workflow_supports_dynamic_agent_and_capability_closures() -> None:
    from noetrium_platform.research.execution.workflow.api import (
        MethodNodeResult,
        MethodWorkflow,
        analyze_method_runtime_requirements,
    )

    program = (
        MethodWorkflow("dynamic-demo")
        .dynamic_agent(
            "delegate",
            ("agent.a", "agent.b"),
            lambda request: "agent.a",
            instruction="Delegate.",
            next="tool",
        )
        .dynamic_capability(
            "tool",
            ("tool.a", "tool.b"),
            lambda request: "tool.b",
            next="finish",
        )
        .return_("finish")
        .build()
    )
    requirements = analyze_method_runtime_requirements(program)
    assert requirements.agent_ids == ("agent.a", "agent.b")
    assert requirements.capability_ids == ("tool.a", "tool.b")
