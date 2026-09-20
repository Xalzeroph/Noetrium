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
    assert sequential.compile().identity.method.method_id == "demo-sequence"
    assert cyclic.compile().identity.method.method_id == "demo-cycle"


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
