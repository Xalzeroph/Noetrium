"""Canonical static Participant semantics over NoetriumUnit."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

PARTICIPANT_REQUIREMENT_TRAIT = "noetrium.participant-requirement"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _tokens(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(_text(row, field) for row in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return rows


def participant_requirement(
    role: str,
    participant_kind: str,
    method_id: str,
    treatment_id: str,
    *,
    capability_requirement_ids: tuple[str, ...] = (),
    configuration_ref_ids: tuple[str, ...] = (),
) -> NoetriumUnit:
    role = _text(role, "participant requirement role")
    participant_kind = _text(participant_kind, "participant requirement kind")
    method_id = _text(method_id, "participant requirement method_id")
    treatment_id = _text(treatment_id, "participant requirement treatment_id")
    capabilities = _tokens(
        capability_requirement_ids,
        "participant capability requirements",
    )
    configurations = _tokens(
        configuration_ref_ids,
        "participant configuration refs",
    )
    return structure_unit(
        f"participant-requirement:{role}",
        traits=(PARTICIPANT_REQUIREMENT_TRAIT,),
        parameters={
            "role": role,
            "participant_kind": participant_kind,
            "method_id": method_id,
            "treatment_id": treatment_id,
            "capability_requirement_ids": capabilities,
            "configuration_ref_ids": configurations,
        },
    )


def require_participant_requirement(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(PARTICIPANT_REQUIREMENT_TRAIT)
    ):
        raise TypeError(
            "participant requirement must be noetrium.participant-requirement Unit"
        )
    return value


def participant_requirement_value(value: NoetriumUnit, name: str):
    return require_participant_requirement(value).parameters[name]


def participant_requirement_role(value: NoetriumUnit) -> str:
    return str(participant_requirement_value(value, "role"))


def participant_requirement_kind(value: NoetriumUnit) -> str:
    return str(participant_requirement_value(value, "participant_kind"))


def participant_requirement_method_id(value: NoetriumUnit) -> str:
    return str(participant_requirement_value(value, "method_id"))


def participant_requirement_treatment_id(value: NoetriumUnit) -> str:
    return str(participant_requirement_value(value, "treatment_id"))


def participant_requirement_capabilities(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(participant_requirement_value(value, "capability_requirement_ids"))


def participant_requirement_configurations(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(participant_requirement_value(value, "configuration_ref_ids"))


__all__ = [
    "PARTICIPANT_REQUIREMENT_TRAIT",
    "participant_requirement",
    "participant_requirement_capabilities",
    "participant_requirement_configurations",
    "participant_requirement_kind",
    "participant_requirement_method_id",
    "participant_requirement_role",
    "participant_requirement_treatment_id",
    "participant_requirement_value",
    "require_participant_requirement",
]
