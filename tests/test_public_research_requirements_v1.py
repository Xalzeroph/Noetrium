from __future__ import annotations

from noetrium import api
from noetrium_platform.research.execution.api import (
    MethodRuntimePort,
    ResearchMethodBuilder,
    analyze_method_runtime_requirements,
)


def _view(call):
    return {"input": call.input_value, "state": call.state}


def _return(call):
    return {"value": call.previous_value}


def _method():
    builder = ResearchMethodBuilder("requirements-test", entrypoint="plan")
    builder.agent(
        "plan",
        "requirements.plan",
        "planner",
        ("act",),
        view=_view,
    )
    builder.capability(
        "act",
        "requirements.act",
        "environment.act",
        ("return",),
        effect="idempotent",
    )
    builder.return_node("return", "requirements.return", _return)
    return builder.build()


def test_requirement_analysis_is_internal_to_execution_layer() -> None:
    assert not hasattr(api, "research_requirements")
    assert not hasattr(api, "execution_authoring")
    requirements = analyze_method_runtime_requirements(_method().program)
    assert MethodRuntimePort.AGENT_LOOP in requirements.ports
    assert MethodRuntimePort.CAPABILITIES in requirements.ports
    assert "environment.act" in requirements.capability_ids
    assert len(requirements.requirement_digest) == 64
