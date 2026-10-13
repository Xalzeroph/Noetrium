"""Canonical static Model capability semantics over NoetriumUnit."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

MODEL_CAPABILITY_REQUIREMENT_TRAIT = "noetrium.model-capability-requirement"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _tokens(values: object, field: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(sorted(_text(row, field) for row in values))
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return rows


def model_capability_requirement_unit(
    role: str,
    *,
    prompt_generation_id: str | None = None,
    prompt_id: str | None = None,
    prompt_digest: str | None = None,
    required_capabilities: tuple[str, ...] = (),
    minimum_context_tokens: int = 1,
    tool_schema_sha256: str | None = None,
    capability_id: str = "generation",
    input_schema_id: str = "model.generation.request.v1",
    output_schema_id: str = "model.generation.response.v1",
) -> NoetriumUnit:
    role = _text(role, "model requirement role")
    capability_id = _text(capability_id, "model requirement capability_id")
    input_schema_id = _text(input_schema_id, "model requirement input_schema_id")
    output_schema_id = _text(output_schema_id, "model requirement output_schema_id")
    generation = capability_id in {"generation", "structured-generation"}
    prompt_fields = (prompt_generation_id, prompt_id, prompt_digest)
    if generation:
        prompt_generation_id = _text(
            prompt_generation_id,
            "model requirement prompt_generation_id",
        )
        prompt_id = _text(prompt_id, "model requirement prompt_id")
        if type(prompt_digest) is not str:
            raise TypeError("model requirement prompt_digest must be text")
        require_sha256(prompt_digest, "model requirement prompt_digest")
    elif any(value is not None for value in prompt_fields):
        raise ValueError(
            "non-generation model requirement must not carry prompt identity"
        )
    capabilities = _tokens(
        required_capabilities,
        "model requirement capabilities",
    )
    if type(minimum_context_tokens) is not int or minimum_context_tokens <= 0:
        raise ValueError("model requirement minimum_context_tokens must be positive")
    if tool_schema_sha256 is not None:
        if not generation:
            raise ValueError(
                "tool schema identity is only valid for generation capabilities"
            )
        require_sha256(tool_schema_sha256, "model requirement tool_schema_sha256")
    return structure_unit(
        role,
        traits=(MODEL_CAPABILITY_REQUIREMENT_TRAIT,),
        parameters={
            "role": role,
            "prompt_generation_id": prompt_generation_id,
            "prompt_id": prompt_id,
            "prompt_digest": prompt_digest,
            "required_capabilities": capabilities,
            "minimum_context_tokens": minimum_context_tokens,
            "tool_schema_sha256": tool_schema_sha256,
            "capability_id": capability_id,
            "input_schema_id": input_schema_id,
            "output_schema_id": output_schema_id,
        },
    )


def require_model_capability_requirement(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(MODEL_CAPABILITY_REQUIREMENT_TRAIT)
    ):
        raise TypeError(
            "model requirement must be noetrium.model-capability-requirement Unit"
        )
    return value


def _value(value: NoetriumUnit, name: str):
    return require_model_capability_requirement(value).parameters[name]


def model_capability_requirement_role(value: NoetriumUnit) -> str:
    return str(_value(value, "role"))


def model_capability_requirement_prompt_generation(value: NoetriumUnit) -> str | None:
    raw = _value(value, "prompt_generation_id")
    return None if raw is None else str(raw)


def model_capability_requirement_prompt_id(value: NoetriumUnit) -> str | None:
    raw = _value(value, "prompt_id")
    return None if raw is None else str(raw)


def model_capability_requirement_prompt_digest(value: NoetriumUnit) -> str | None:
    raw = _value(value, "prompt_digest")
    return None if raw is None else str(raw)


def model_capability_requirement_capabilities(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(_value(value, "required_capabilities"))


def model_capability_requirement_minimum_context(value: NoetriumUnit) -> int:
    return int(_value(value, "minimum_context_tokens"))


def model_capability_requirement_tool_schema(value: NoetriumUnit) -> str | None:
    raw = _value(value, "tool_schema_sha256")
    return None if raw is None else str(raw)


def model_capability_requirement_capability(value: NoetriumUnit) -> str:
    return str(_value(value, "capability_id"))


def model_capability_requirement_input_schema(value: NoetriumUnit) -> str:
    return str(_value(value, "input_schema_id"))


def model_capability_requirement_output_schema(value: NoetriumUnit) -> str:
    return str(_value(value, "output_schema_id"))


def model_capability_requirement_is_generation(value: NoetriumUnit) -> bool:
    return model_capability_requirement_capability(value) in {
        "generation",
        "structured-generation",
    }


def model_capability_requirement_digest(value: NoetriumUnit) -> str:
    return require_model_capability_requirement(value).unit_digest


__all__ = [
    "MODEL_CAPABILITY_REQUIREMENT_TRAIT",
    "model_capability_requirement_unit",
    "model_capability_requirement_capabilities",
    "model_capability_requirement_capability",
    "model_capability_requirement_digest",
    "model_capability_requirement_input_schema",
    "model_capability_requirement_is_generation",
    "model_capability_requirement_minimum_context",
    "model_capability_requirement_output_schema",
    "model_capability_requirement_prompt_digest",
    "model_capability_requirement_prompt_generation",
    "model_capability_requirement_prompt_id",
    "model_capability_requirement_role",
    "model_capability_requirement_tool_schema",
    "require_model_capability_requirement",
]


MULTIMODAL_METHOD_TRAIT = "model.multimodal-method"


def multimodal_method_unit(
    method_id: str,
    revision: str,
    input_schema_id: str,
    output_schema_id: str,
    *,
    input_modalities: tuple[str, ...] = (),
    output_modalities: tuple[str, ...] = (),
    parameters=None,
) -> NoetriumUnit:
    from noetrium_platform.foundation.kernel.kernel import freeze_json
    method_id = _text(method_id, "multimodal method_id")
    revision = _text(revision, "multimodal revision")
    input_schema_id = _text(input_schema_id, "multimodal input_schema_id")
    output_schema_id = _text(output_schema_id, "multimodal output_schema_id")
    inputs = _tokens(input_modalities, "multimodal input modalities")
    outputs = _tokens(output_modalities, "multimodal output modalities")
    parameters = {} if parameters is None else dict(parameters)
    return structure_unit(
        method_id,
        traits=(MULTIMODAL_METHOD_TRAIT,),
        parameters={
            "revision": revision,
            "input_schema_id": input_schema_id,
            "output_schema_id": output_schema_id,
            "input_modalities": inputs,
            "output_modalities": outputs,
            "parameters": freeze_json(parameters),
        },
    )


def require_multimodal_method(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(MULTIMODAL_METHOD_TRAIT):
        raise TypeError("multimodal method must be model.multimodal-method Unit")
    return value


def multimodal_method_id(value: NoetriumUnit) -> str:
    return require_multimodal_method(value).unit_id


def multimodal_method_revision(value: NoetriumUnit) -> str:
    return str(require_multimodal_method(value).parameters["revision"])


def multimodal_method_input_schema(value: NoetriumUnit) -> str:
    return str(require_multimodal_method(value).parameters["input_schema_id"])


def multimodal_method_output_schema(value: NoetriumUnit) -> str:
    return str(require_multimodal_method(value).parameters["output_schema_id"])


def multimodal_method_input_modalities(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(require_multimodal_method(value).parameters["input_modalities"])


def multimodal_method_output_modalities(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(require_multimodal_method(value).parameters["output_modalities"])


def multimodal_method_parameters(value: NoetriumUnit):
    return require_multimodal_method(value).parameters["parameters"]


def multimodal_method_digest(value: NoetriumUnit) -> str:
    return require_multimodal_method(value).unit_digest


__all__ += [
    "MULTIMODAL_METHOD_TRAIT",
    "multimodal_method_unit",
    "multimodal_method_id",
    "multimodal_method_revision",
    "multimodal_method_input_schema",
    "multimodal_method_output_schema",
    "multimodal_method_input_modalities",
    "multimodal_method_output_modalities",
    "multimodal_method_parameters",
    "multimodal_method_digest",
    "require_multimodal_method",
]
