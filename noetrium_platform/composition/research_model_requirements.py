from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
    ResearchProgram,
)
from noetrium_platform.research.experimentation.api import (
    ResearchModelRoleRequirement,
)


@dataclass(frozen=True, slots=True)
class ResearchModelRequirementSemantics:
    requirement: ResearchModelRoleRequirement
    model_definition: object
    model_config: Mapping[str, object]
    required_models: tuple[str, ...]
    prompt_definition: object
    prompt_config: Mapping[str, object]
    prompt_generation_id: str
    prompt_id: str

    @property
    def structured_output(self) -> bool:
        return bool(self.model_config.get("structured_output", False))


def _definition(
    program: ResearchProgram,
    definition_id: str,
    kind: ResearchDefinitionKind,
):
    matches = tuple(
        row
        for row in program.definitions
        if row.definition_id == definition_id and row.kind is kind
    )
    if len(matches) != 1:
        raise LookupError(
            f"ResearchProgram has no unique {kind.value} definition "
            f"for {definition_id!r}"
        )
    return matches[0]


def research_model_requirement_semantics(
    program: ResearchProgram,
    requirement: ResearchModelRoleRequirement,
) -> ResearchModelRequirementSemantics:
    if type(program) is not ResearchProgram:
        raise TypeError("model requirement semantics requires ResearchProgram")
    if not isinstance(requirement, ResearchModelRoleRequirement):
        raise TypeError(
            "model requirement semantics requires ResearchModelRoleRequirement"
        )

    model_definition = _definition(
        program,
        requirement.requirement_id,
        ResearchDefinitionKind.MODEL,
    )
    if not isinstance(model_definition.config, Mapping):
        raise TypeError("Research Model definition config must be an object")
    model_config = dict(model_definition.config)

    # Functional Study roles belong to ResearchModelRoleRequirement. The Model
    # definition owns the scientific model/panel identity and may be reused by
    # multiple roles with different prompt configurations.
    single = model_config.get("required_model")
    panel = model_config.get("required_models")
    if single is not None and panel is not None:
        raise ValueError(
            "Research Model definition must declare required_model or "
            "required_models, not both"
        )
    if panel is None:
        if type(single) is not str or not single.strip():
            raise ValueError(
                "Research Model definition requires required_model or "
                "required_models"
            )
        required_models = (single.strip(),)
    else:
        if not isinstance(panel, (tuple, list)) or not panel:
            raise TypeError(
                "Research Model required_models must be a non-empty sequence"
            )
        if any(type(row) is not str or not row.strip() for row in panel):
            raise TypeError(
                "Research Model required_models must contain non-empty text"
            )
        required_models = tuple(row.strip() for row in panel)
        if len(required_models) != len(set(required_models)):
            raise ValueError("Research Model required_models must be unique")

    if (
        requirement.max_bindings is not None
        and len(required_models) > requirement.max_bindings
    ):
        raise ValueError(
            f"model role {requirement.role!r} declares "
            f"{len(required_models)} scientific members but "
            f"max_bindings={requirement.max_bindings}"
        )

    prompt_configuration_id = requirement.prompt_configuration_id
    if type(prompt_configuration_id) is not str or not prompt_configuration_id:
        raise ValueError(
            "generation Model role requires prompt configuration identity"
        )
    prompt_definition = _definition(
        program,
        prompt_configuration_id,
        ResearchDefinitionKind.CONFIGURATION,
    )
    if not isinstance(prompt_definition.config, Mapping):
        raise TypeError("Research prompt configuration must be an object")
    prompt_config = dict(prompt_definition.config)
    prompt_generation_id = prompt_config.get(
        "prompt_generation_id",
        prompt_configuration_id,
    )
    prompt_id = prompt_config.get("prompt_id", prompt_configuration_id)
    if type(prompt_generation_id) is not str or not prompt_generation_id:
        raise ValueError("prompt generation identity is required")
    if type(prompt_id) is not str or not prompt_id:
        raise ValueError("prompt identity is required")

    return ResearchModelRequirementSemantics(
        requirement=requirement,
        model_definition=model_definition,
        model_config=model_config,
        required_models=required_models,
        prompt_definition=prompt_definition,
        prompt_config=prompt_config,
        prompt_generation_id=prompt_generation_id,
        prompt_id=prompt_id,
    )


__all__ = [
    "ResearchModelRequirementSemantics",
    "research_model_requirement_semantics",
]
