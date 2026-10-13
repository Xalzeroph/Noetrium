"""Canonical immutable Prompt semantics over NoetriumUnit."""
from __future__ import annotations

import math
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonInput, JsonObject, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

PROMPT_SECTION_TRAIT = "model.prompt-section"
PROMPT_TRAIT = "model.prompt"
OUTPUT_SCHEMA_TRAIT = "model.output-schema"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def prompt_section_unit(section_id: str, text: str, priority: int) -> NoetriumUnit:
    section_id = _text(section_id, "prompt section_id")
    if type(text) is not str or not text.strip():
        raise ValueError("prompt section text must be non-empty")
    if type(priority) is not int:
        raise TypeError("prompt section priority must be integer")
    return structure_unit(
        section_id,
        traits=(PROMPT_SECTION_TRAIT,),
        parameters={"text": text, "priority": priority},
    )


def require_prompt_section(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(PROMPT_SECTION_TRAIT):
        raise TypeError("prompt section must be model.prompt-section Unit")
    return value


def prompt_section_text(value: NoetriumUnit) -> str:
    return str(require_prompt_section(value).parameters["text"])


def prompt_section_priority(value: NoetriumUnit) -> int:
    return int(require_prompt_section(value).parameters["priority"])


def prompt_unit(
    prompt_id: str,
    role: str,
    version: str,
    model_family: str,
    output_schema_id: str,
    sections: tuple[NoetriumUnit, ...],
    temperature: float,
    top_p: float,
    max_output_tokens: int,
) -> NoetriumUnit:
    prompt_id = _text(prompt_id, "prompt_id")
    role = _text(role, "prompt role")
    version = _text(version, "prompt version")
    model_family = _text(model_family, "prompt model_family")
    output_schema_id = _text(output_schema_id, "prompt output_schema_id")
    if type(sections) is not tuple or not sections:
        raise ValueError("prompt requires at least one section")
    for section in sections:
        require_prompt_section(section)
    section_ids = tuple(section.unit_id for section in sections)
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("prompt section ids must be unique")
    for name, value in (("temperature", temperature), ("top_p", top_p)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"prompt {name} must be finite")
    if float(temperature) < 0:
        raise ValueError("prompt temperature must be non-negative")
    if not 0 < float(top_p) <= 1:
        raise ValueError("prompt top_p must be within (0, 1]")
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise ValueError("prompt max_output_tokens must be positive")
    ordered = tuple(sorted(sections, key=lambda row: (prompt_section_priority(row), row.unit_id)))
    return structure_unit(
        prompt_id,
        traits=(PROMPT_TRAIT,),
        parameters={
            "role": role,
            "version": version,
            "model_family": model_family,
            "output_schema_id": output_schema_id,
            "temperature": float(temperature),
            "top_p": float(top_p),
            "max_output_tokens": max_output_tokens,
        },
        members=ordered,
    )


def require_prompt_unit(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(PROMPT_TRAIT):
        raise TypeError("prompt must be model.prompt Unit")
    return value


def prompt_id(value: NoetriumUnit) -> str:
    return require_prompt_unit(value).unit_id


def prompt_role(value: NoetriumUnit) -> str:
    return str(require_prompt_unit(value).parameters["role"])


def prompt_version(value: NoetriumUnit) -> str:
    return str(require_prompt_unit(value).parameters["version"])


def prompt_model_family(value: NoetriumUnit) -> str:
    return str(require_prompt_unit(value).parameters["model_family"])


def prompt_output_schema_id(value: NoetriumUnit) -> str:
    return str(require_prompt_unit(value).parameters["output_schema_id"])


def prompt_sections(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    prompt = require_prompt_unit(value)
    rows = tuple(row for row in prompt.members if row.has_trait(PROMPT_SECTION_TRAIT))
    if len(rows) != len(prompt.members):
        raise ValueError("prompt contains non-section members")
    return rows


def prompt_temperature(value: NoetriumUnit) -> float:
    return float(require_prompt_unit(value).parameters["temperature"])


def prompt_top_p(value: NoetriumUnit) -> float:
    return float(require_prompt_unit(value).parameters["top_p"])


def prompt_max_output_tokens(value: NoetriumUnit) -> int:
    return int(require_prompt_unit(value).parameters["max_output_tokens"])


def compile_prompt_text(value: NoetriumUnit) -> str:
    return "\n\n".join(
        prompt_section_text(row).strip()
        for row in sorted(
            prompt_sections(value),
            key=lambda row: (prompt_section_priority(row), row.unit_id),
        )
    ) + "\n"


def prompt_bundle_digest(value: NoetriumUnit) -> str:
    return require_prompt_unit(value).unit_digest


def output_schema_unit(
    schema_id: str,
    version: str,
    schema: Mapping[str, JsonInput],
) -> NoetriumUnit:
    schema_id = _text(schema_id, "output schema_id")
    version = _text(version, "output schema version")
    if not isinstance(schema, Mapping):
        raise TypeError("output schema must be mapping")
    return structure_unit(
        schema_id,
        traits=(OUTPUT_SCHEMA_TRAIT,),
        parameters={"version": version, "schema": freeze_json(schema)},
    )


def require_output_schema(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(OUTPUT_SCHEMA_TRAIT):
        raise TypeError("output schema must be model.output-schema Unit")
    return value


def output_schema_id(value: NoetriumUnit) -> str:
    return require_output_schema(value).unit_id


def output_schema_version(value: NoetriumUnit) -> str:
    return str(require_output_schema(value).parameters["version"])


def output_schema_document(value: NoetriumUnit) -> JsonObject:
    schema = require_output_schema(value).parameters["schema"]
    if not isinstance(schema, Mapping):
        raise TypeError("output schema document must be mapping")
    return schema


def output_schema_digest(value: NoetriumUnit) -> str:
    return require_output_schema(value).unit_digest


__all__ = [
    "OUTPUT_SCHEMA_TRAIT",
    "PROMPT_SECTION_TRAIT",
    "PROMPT_TRAIT",
    "compile_prompt_text",
    "output_schema_digest",
    "output_schema_document",
    "output_schema_id",
    "output_schema_unit",
    "output_schema_version",
    "prompt_bundle_digest",
    "prompt_id",
    "prompt_max_output_tokens",
    "prompt_model_family",
    "prompt_output_schema_id",
    "prompt_role",
    "prompt_section_priority",
    "prompt_section_text",
    "prompt_section_unit",
    "prompt_sections",
    "prompt_temperature",
    "prompt_top_p",
    "prompt_unit",
    "prompt_version",
    "require_output_schema",
    "require_prompt_section",
    "require_prompt_unit",
]
