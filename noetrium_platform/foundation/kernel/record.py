"""Record/evidence/event schemas over the sole persistent semantic carrier.

NoetriumUnit is the only persisted semantic object. A record is a schema over
that carrier; record/evidence/journal/observation are modalities/roles, never a
parallel object universe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit


RECORD_SCHEMA = "record"
RECORD_KIND = "record"


class RecordRole(StrEnum):
    JOURNAL = "journal"
    EVIDENCE = "evidence"
    ARTIFACT = "artifact"
    OBSERVATION = "observation"
    FACT = "fact"
    METRIC = "metric"
    ERROR = "error"


class GraphSubjectFacet(StrEnum):
    GRAPH = "graph"
    NODE = "node"
    RELATION = "relation"
    EXECUTION_CUT = "execution_cut"
    BOUNDARY = "boundary"
    EFFECT = "effect"
    REQUIREMENT = "requirement"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class GraphSubjectRef:
    """Ephemeral typed value used to construct/project record Units."""

    graph_semantic_digest: str
    element_id: str
    facet: GraphSubjectFacet = GraphSubjectFacet.GRAPH

    def __post_init__(self) -> None:
        require_sha256(self.graph_semantic_digest, "record graph semantic digest")
        if type(self.element_id) is not str or not self.element_id.strip():
            raise ValueError("record graph element_id must be non-empty")
        if not isinstance(self.facet, GraphSubjectFacet):
            raise TypeError("record graph subject facet must be typed")


@dataclass(frozen=True, slots=True)
class RecordContentRef:
    """Ephemeral typed value used to construct/project record Units."""

    content_digest: str
    media_type: str = "application/octet-stream"
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        require_sha256(self.content_digest, "record content digest")
        if type(self.media_type) is not str or not self.media_type.strip():
            raise ValueError("record media_type must be non-empty")
        if self.size_bytes is not None and (
            type(self.size_bytes) is not int or self.size_bytes < 0
        ):
            raise ValueError("record size_bytes must be non-negative int")


def _subject_document(subject: GraphSubjectRef | None) -> object:
    if subject is None:
        return None
    if type(subject) is not GraphSubjectRef:
        raise TypeError("record subject must be GraphSubjectRef")
    return {
        "graph_semantic_digest": subject.graph_semantic_digest,
        "element_id": subject.element_id,
        "facet": subject.facet.value,
    }


def _content_document(content: RecordContentRef | None) -> object:
    if content is None:
        return None
    if type(content) is not RecordContentRef:
        raise TypeError("record content must be RecordContentRef")
    return {
        "content_digest": content.content_digest,
        "media_type": content.media_type,
        "size_bytes": content.size_bytes,
    }


def record_unit(
    record_type_value: str,
    roles: frozenset[RecordRole],
    subject: GraphSubjectRef | None = None,
    payload: JsonValue = None,
    provenance: JsonValue = None,
    caused_by: tuple[str, ...] = (),
    content: RecordContentRef | None = None,
    record_id_value: str | None = None,
    observed_at: float | None = None,
) -> NoetriumUnit:
    if type(record_type_value) is not str or not record_type_value.strip():
        raise ValueError("record_type must be non-empty")
    if (
        type(roles) is not frozenset
        or not roles
        or any(not isinstance(role, RecordRole) for role in roles)
    ):
        raise TypeError("record roles must be a non-empty RecordRole frozenset")
    if record_id_value is not None and (
        type(record_id_value) is not str or not record_id_value.strip()
    ):
        raise ValueError("record_id must be non-empty when present")
    if observed_at is not None and not math.isfinite(float(observed_at)):
        raise ValueError("record observed_at must be finite")
    if type(caused_by) is not tuple:
        raise TypeError("record caused_by must be tuple")
    for digest in caused_by:
        require_sha256(digest, "record cause digest")
    if len(caused_by) != len(set(caused_by)):
        raise ValueError("record causes must be unique")

    frozen_payload = freeze_json({} if payload is None else payload)
    frozen_provenance = freeze_json({} if provenance is None else provenance)
    if not isinstance(frozen_payload, Mapping) or not isinstance(
        frozen_provenance, Mapping
    ):
        raise TypeError("record payload/provenance must be objects")

    attributes = {
        "kind": RECORD_KIND,
        "record_type": record_type_value.strip(),
        "roles": tuple(sorted(role.value for role in roles)),
        "subject": _subject_document(subject),
        "payload": frozen_payload,
        "provenance": frozen_provenance,
        "caused_by": tuple(sorted(caused_by)),
        "content": _content_document(content),
        "record_id": record_id_value,
        "observed_at": observed_at,
    }
    semantic = canonical_digest(attributes)
    return NoetriumUnit(
        unit_id=f"record:{semantic}",
        schemas=(RECORD_SCHEMA,),
        attributes=attributes,
    )


def _require_record(record: NoetriumUnit) -> NoetriumUnit:
    if type(record) is not NoetriumUnit or not record.has_schema(RECORD_SCHEMA):
        raise TypeError("record must be a record NoetriumUnit")
    if record.attributes.get("kind") != RECORD_KIND:
        raise TypeError("record Unit kind is invalid")
    return record


def record_type(record: NoetriumUnit) -> str:
    value = _require_record(record).attributes.get("record_type")
    if type(value) is not str or not value:
        raise TypeError("record_type projection is invalid")
    return value


def record_roles(record: NoetriumUnit) -> frozenset[RecordRole]:
    values = _require_record(record).attributes.get("roles")
    if type(values) is not tuple:
        raise TypeError("record roles projection is invalid")
    return frozenset(RecordRole(value) for value in values)


def record_has_role(record: NoetriumUnit, role: RecordRole) -> bool:
    if not isinstance(role, RecordRole):
        raise TypeError("record role query must be RecordRole")
    return role in record_roles(record)


def record_subject(record: NoetriumUnit) -> GraphSubjectRef | None:
    value = _require_record(record).attributes.get("subject")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("record subject projection is invalid")
    return GraphSubjectRef(
        graph_semantic_digest=str(value["graph_semantic_digest"]),
        element_id=str(value["element_id"]),
        facet=GraphSubjectFacet(str(value["facet"])),
    )


def record_payload(record: NoetriumUnit) -> Mapping[str, JsonValue]:
    value = _require_record(record).attributes.get("payload")
    if not isinstance(value, Mapping):
        raise TypeError("record payload projection is invalid")
    return value


def record_provenance(record: NoetriumUnit) -> Mapping[str, JsonValue]:
    value = _require_record(record).attributes.get("provenance")
    if not isinstance(value, Mapping):
        raise TypeError("record provenance projection is invalid")
    return value


def record_caused_by(record: NoetriumUnit) -> tuple[str, ...]:
    value = _require_record(record).attributes.get("caused_by")
    if type(value) is not tuple or any(type(row) is not str for row in value):
        raise TypeError("record caused_by projection is invalid")
    return value


def record_content(record: NoetriumUnit) -> RecordContentRef | None:
    value = _require_record(record).attributes.get("content")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("record content projection is invalid")
    return RecordContentRef(
        content_digest=str(value["content_digest"]),
        media_type=str(value["media_type"]),
        size_bytes=value.get("size_bytes"),
    )


def record_id(record: NoetriumUnit) -> str | None:
    value = _require_record(record).attributes.get("record_id")
    if value is None:
        return None
    if type(value) is not str or not value:
        raise TypeError("record_id projection is invalid")
    return value


def record_observed_at(record: NoetriumUnit) -> float | None:
    value = _require_record(record).attributes.get("observed_at")
    if value is None:
        return None
    return float(value)


def record_digest(record: NoetriumUnit) -> str:
    return _require_record(record).semantic_digest


def evidence_record(
    record_type_value: str,
    *,
    payload: JsonValue,
    subject: GraphSubjectRef | None = None,
    provenance: JsonValue = None,
    caused_by: tuple[str, ...] = (),
    journal: bool = False,
) -> NoetriumUnit:
    roles = {RecordRole.EVIDENCE}
    if journal:
        roles.add(RecordRole.JOURNAL)
    return record_unit(
        record_type_value,
        frozenset(roles),
        subject,
        payload,
        provenance,
        caused_by,
    )


def journal_record(
    record_type_value: str,
    *,
    payload: JsonValue,
    subject: GraphSubjectRef | None = None,
    provenance: JsonValue = None,
    caused_by: tuple[str, ...] = (),
) -> NoetriumUnit:
    return record_unit(
        record_type_value,
        frozenset({RecordRole.JOURNAL}),
        subject,
        payload,
        provenance,
        caused_by,
    )


def artifact_record(
    record_type_value: str,
    *,
    content: RecordContentRef,
    payload: JsonValue = None,
    subject: GraphSubjectRef | None = None,
    provenance: JsonValue = None,
    caused_by: tuple[str, ...] = (),
) -> NoetriumUnit:
    return record_unit(
        record_type_value,
        frozenset({RecordRole.ARTIFACT}),
        subject,
        payload,
        provenance,
        caused_by,
        content,
    )


def observation_record(
    record_type_value: str,
    *,
    record_id: str,
    payload: JsonValue,
    provenance: JsonValue = None,
    subject: GraphSubjectRef | None = None,
    caused_by: tuple[str, ...] = (),
    observed_at: float | None = None,
) -> NoetriumUnit:
    return record_unit(
        record_type_value,
        frozenset({RecordRole.OBSERVATION, RecordRole.EVIDENCE}),
        subject,
        payload,
        provenance,
        caused_by,
        None,
        record_id,
        observed_at,
    )


def record_document(record: NoetriumUnit) -> dict[str, object]:
    subject = record_subject(record)
    content = record_content(record)
    return {
        "record_type": record_type(record),
        "roles": tuple(sorted(role.value for role in record_roles(record))),
        "subject": (
            None
            if subject is None
            else {
                "graph_semantic_digest": subject.graph_semantic_digest,
                "element_id": subject.element_id,
                "facet": subject.facet.value,
            }
        ),
        "payload": thaw_json(record_payload(record)),
        "provenance": thaw_json(record_provenance(record)),
        "caused_by": record_caused_by(record),
        "content": (
            None
            if content is None
            else {
                "content_digest": content.content_digest,
                "media_type": content.media_type,
                "size_bytes": content.size_bytes,
            }
        ),
        "record_id": record_id(record),
        "observed_at": record_observed_at(record),
        "record_digest": record_digest(record),
    }


@dataclass(frozen=True, slots=True)
class RecordRequirement:
    """Ephemeral predicate over record Units."""

    requirement_id: str
    accepted_record_types: tuple[str, ...]
    required_roles: frozenset[RecordRole] = frozenset({RecordRole.EVIDENCE})

    def __post_init__(self) -> None:
        if not self.requirement_id.strip() or not self.accepted_record_types:
            raise ValueError("record requirement must be non-empty")
        if len(self.accepted_record_types) != len(set(self.accepted_record_types)):
            raise ValueError("accepted record types must be unique")

    def satisfied_by(self, record: NoetriumUnit) -> bool:
        return (
            record_type(record) in self.accepted_record_types
            and self.required_roles <= record_roles(record)
        )


__all__ = [
    "artifact_record",
    "evidence_record",
    "GraphSubjectFacet",
    "GraphSubjectRef",
    "journal_record",
    "observation_record",
    "RecordContentRef",
    "RecordRequirement",
    "RecordRole",
    "record_caused_by",
    "record_content",
    "record_digest",
    "record_document",
    "record_has_role",
    "record_id",
    "record_observed_at",
    "record_payload",
    "record_provenance",
    "record_roles",
    "record_subject",
    "record_type",
    "record_unit",
]
