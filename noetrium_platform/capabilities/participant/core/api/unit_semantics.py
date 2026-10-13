"""Canonical static participant implementation semantics over NoetriumUnit."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

PARTICIPANT_IMPLEMENTATION_TRAIT = "participant.implementation"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def participant_implementation_unit(
    kind: str,
    participant_id: str,
    implementation_version: str,
    abi_version: str,
    schema_version: str,
    artifact_digest: str | None = None,
) -> NoetriumUnit:
    kind = _text(kind, "participant implementation kind")
    participant_id = _text(participant_id, "participant implementation id")
    implementation_version = _text(
        implementation_version,
        "participant implementation version",
    )
    abi_version = _text(abi_version, "participant implementation ABI")
    schema_version = _text(schema_version, "participant implementation schema")
    if artifact_digest is not None:
        require_sha256(artifact_digest, "participant implementation artifact_digest")
    return structure_unit(
        participant_id,
        traits=(PARTICIPANT_IMPLEMENTATION_TRAIT,),
        parameters={
            "kind": kind,
            "implementation_version": implementation_version,
            "abi_version": abi_version,
            "schema_version": schema_version,
            "artifact_digest": artifact_digest,
        },
    )


def require_participant_implementation(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(PARTICIPANT_IMPLEMENTATION_TRAIT)
    ):
        raise TypeError(
            "participant implementation must be participant.implementation Unit"
        )
    return value


def participant_implementation_kind(value: NoetriumUnit) -> str:
    return str(require_participant_implementation(value).parameters["kind"])


def participant_implementation_id(value: NoetriumUnit) -> str:
    return require_participant_implementation(value).unit_id


def participant_implementation_version(value: NoetriumUnit) -> str:
    return str(
        require_participant_implementation(value).parameters["implementation_version"]
    )


def participant_implementation_abi(value: NoetriumUnit) -> str:
    return str(require_participant_implementation(value).parameters["abi_version"])


def participant_implementation_schema(value: NoetriumUnit) -> str:
    return str(require_participant_implementation(value).parameters["schema_version"])


def participant_implementation_artifact(value: NoetriumUnit) -> str | None:
    raw = require_participant_implementation(value).parameters["artifact_digest"]
    return None if raw is None else str(raw)


def participant_implementation_digest(value: NoetriumUnit) -> str:
    return require_participant_implementation(value).unit_digest


__all__ = [
    "PARTICIPANT_IMPLEMENTATION_TRAIT",
    "participant_implementation_abi",
    "participant_implementation_artifact",
    "participant_implementation_digest",
    "participant_implementation_id",
    "participant_implementation_kind",
    "participant_implementation_schema",
    "participant_implementation_unit",
    "participant_implementation_version",
    "require_participant_implementation",
]
