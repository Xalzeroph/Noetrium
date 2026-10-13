"""Environment projections onto the one immutable NoetriumUnit calculus."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.record import (
    GraphSubjectRef,
    RecordRole,
    record_unit,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit


def environment_observation_record(
    *,
    observation_id: str,
    generation: str,
    payload: JsonValue,
    subject: GraphSubjectRef | None = None,
    artifact_refs: tuple[str, ...] = (),
    caused_by: tuple[str, ...] = (),
) -> NoetriumUnit:
    return record_unit(
        "environment.observation",
        frozenset({RecordRole.JOURNAL, RecordRole.EVIDENCE}),
        subject,
        {
            "observation_id": observation_id,
            "generation": generation,
            "payload": payload,
            "artifact_refs": artifact_refs,
        },
        {"source": "environment"},
        caused_by,
    )


def environment_effect_record(
    *,
    action_id: str,
    disposition: str,
    payload: JsonValue = None,
    subject: GraphSubjectRef | None = None,
    caused_by: tuple[str, ...] = (),
) -> NoetriumUnit:
    return record_unit(
        "environment.effect",
        frozenset({RecordRole.JOURNAL, RecordRole.EVIDENCE}),
        subject,
        {
            "action_id": action_id,
            "disposition": disposition,
            "payload": {} if payload is None else payload,
        },
        {"source": "environment"},
        caused_by,
    )


__all__ = ["environment_effect_record", "environment_observation_record"]
