from __future__ import annotations

from noetrium import api
from noetrium_platform.composition.research_model_requirements import (
    research_model_requirement_semantics,
)
from noetrium_platform.research.experimentation.api import (
    ResearchModelRoleRequirement,
)


def _noop():
    return {"ok": True}


def _program():
    portfolio = api.ResearchPortfolioBuilder("model-role-fixture")
    program = portfolio.program("model-role-fixture")
    program.model(
        "shared-model",
        config={
            "role": "shared-physical-model",
            "required_model": "Qwen3-8B",
            "structured_output": True,
        },
    )
    program.configuration(
        "planner-prompt",
        config={
            "prompt_id": "planner",
            "prompt_generation_id": "planner-v1",
        },
    )
    program.configuration(
        "meta-prompt",
        config={
            "prompt_id": "meta",
            "prompt_generation_id": "meta-v1",
        },
    )
    program.custom_definition("noop", implementation=_noop)
    program.custom_node("noop", definitions=("noop",))
    return portfolio.freeze().programs[0]


def test_one_model_definition_can_serve_multiple_study_roles() -> None:
    program = _program()
    planner = research_model_requirement_semantics(
        program,
        ResearchModelRoleRequirement(
            role="planner",
            requirement_id="shared-model",
            prompt_configuration_id="planner-prompt",
        ),
    )
    meta = research_model_requirement_semantics(
        program,
        ResearchModelRoleRequirement(
            role="meta-architect",
            requirement_id="shared-model",
            prompt_configuration_id="meta-prompt",
        ),
    )

    assert planner.required_models == meta.required_models == ("Qwen3-8B",)
    assert planner.requirement.role == "planner"
    assert meta.requirement.role == "meta-architect"
    assert planner.prompt_generation_id == "planner-v1"
    assert meta.prompt_generation_id == "meta-v1"


def test_binding_resolver_delegates_model_semantics_to_single_authority() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (
        root
        / "noetrium_platform/composition/local_research_execution_authority.py"
    ).read_text(encoding="utf-8")
    block = source.split("    def _qualified_bindings(", 1)[1].split(
        "    def _project_model_binding(", 1
    )[0]
    assert "research_model_requirement_semantics(program, requirement)" in block
    assert 'model_config.get("role")' not in block
    assert 'model_config.get("required_model")' not in block
