from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.product.research_traits import (
    TRAIT_CONFIGURATION,
    TRAIT_MODEL,
)
from noetrium_platform.research.experimentation.binding import (
    model_role_requirement_capabilities,
    model_role_requirement_capability,
    model_role_requirement_id,
    model_role_requirement_input_schema,
    model_role_requirement_max_bindings,
    model_role_requirement_minimum_context,
    model_role_requirement_output_schema,
    model_role_requirement_prompt,
    model_role_requirement_role,
    require_model_role_requirement,
)


def _definition(
    program: NoetriumUnit,
    definition_id: str,
    trait_id: str,
) -> NoetriumUnit:
    row = program.symbol(definition_id)
    if not row.has_trait(trait_id):
        raise LookupError(
            f"NoetriumUnit symbol {definition_id!r} does not declare {trait_id!r}"
        )
    return row


def research_model_binding_units(
    program: NoetriumUnit,
    requirement: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    """Derive exact static model-role bindings directly from the research Unit."""

    if type(program) is not NoetriumUnit:
        raise TypeError("model requirement binding requires NoetriumUnit")
    require_model_role_requirement(requirement)

    model_definition = _definition(
        program,
        model_role_requirement_id(requirement),
        TRAIT_MODEL,
    )
    if not isinstance(model_definition.parameters, Mapping):
        raise TypeError("Research Model definition config must be an object")
    model_config = dict(model_definition.parameters)

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

    maximum = model_role_requirement_max_bindings(requirement)
    if maximum is not None and len(required_models) > maximum:
        raise ValueError(
            f"model role {model_role_requirement_role(requirement)!r} declares "
            f"{len(required_models)} scientific members but max_bindings={maximum}"
        )

    generation = model_role_requirement_capability(requirement) in {
        "generation",
        "structured-generation",
    }
    prompt_configuration_id = model_role_requirement_prompt(requirement)
    prompt_definition: NoetriumUnit | None
    prompt_generation_id: str | None

    if generation:
        if type(prompt_configuration_id) is not str or not prompt_configuration_id:
            raise ValueError(
                "generation Model role requires prompt configuration identity"
            )
        prompt_definition = _definition(
            program,
            prompt_configuration_id,
            TRAIT_CONFIGURATION,
        )
        if not isinstance(prompt_definition.parameters, Mapping):
            raise TypeError("Research prompt configuration must be an object")
        prompt_config = dict(prompt_definition.parameters)
        prompt_generation_id = prompt_config.get(
            "prompt_generation_id",
            prompt_configuration_id,
        )
        prompt_id = prompt_config.get("prompt_id", prompt_configuration_id)
        if type(prompt_generation_id) is not str or not prompt_generation_id:
            raise ValueError("prompt generation identity is required")
        if type(prompt_id) is not str or not prompt_id:
            raise ValueError("prompt identity is required")
    else:
        if prompt_configuration_id is not None:
            raise ValueError(
                "non-generation Model role cannot carry prompt configuration"
            )
        prompt_definition = None
        prompt_generation_id = None

    capabilities = set(model_role_requirement_capabilities(requirement))
    if generation:
        capabilities.add("generation")
    if (
        model_role_requirement_capability(requirement) == "structured-generation"
        or (generation and bool(model_config.get("structured_output", False)))
    ):
        capabilities.add("structured_output")
    frozen_capabilities = tuple(sorted(capabilities))
    prompt_digest = (
        None
        if prompt_definition is None
        else prompt_definition.symbol_digest
    )

    rows = []
    for member_index, model_id in enumerate(required_models):
        params = {
            "requirement_id": model_role_requirement_id(requirement),
            "requirement_digest": requirement.unit_digest,
            "role": model_role_requirement_role(requirement),
            "member_index": member_index,
            "model_id": model_id,
            "model_definition_digest": model_definition.symbol_digest,
            "prompt_generation_id": prompt_generation_id,
            "prompt_digest": prompt_digest,
            "capabilities": frozen_capabilities,
            "minimum_context_tokens": model_role_requirement_minimum_context(requirement),
            "capability_id": model_role_requirement_capability(requirement),
            "input_schema_id": model_role_requirement_input_schema(requirement),
            "output_schema_id": model_role_requirement_output_schema(requirement),
        }
        members = (model_definition,)
        if prompt_definition is not None:
            members += (prompt_definition,)
        rows.append(
            structure_unit(
                (
                    "research-model-binding:"
                    + model_role_requirement_role(requirement)
                    + ":"
                    + str(member_index)
                ),
                traits=("research.model-binding",),
                parameters=params,
                members=members,
            )
        )
    return tuple(rows)


__all__ = ["research_model_binding_units"]
