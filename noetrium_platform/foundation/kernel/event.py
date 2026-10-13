"""Causal event trace algebra over NoetriumUnit.

Events are not a second carrier. An event is exactly a NoetriumUnit satisfying
system.event and the invariants below. Ordering is causal/domain-local; there is
intentionally no global sequence number.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json

from .dag import deterministic_topological_order
from .truth import TruthModality, modal_attributes, truth_modality
from .unit import NoetriumUnit, UnitRef, UnitRoleValue, role, unit_token


EVENT_SCHEMA = "system.event"
_EVENT_REF_PREFIX = "event:"


def _texts(values: Iterable[str], field: str) -> tuple[str, ...]:
    rows = tuple(str(value).strip() for value in values)
    if any(not value for value in rows):
        raise ValueError(f"{field} must contain non-empty text")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return tuple(sorted(rows))


def event_ref(event: NoetriumUnit) -> UnitRef:
    require_event_unit(event)
    return event_ref_from_digest(event.unit_digest)


def event_ref_from_digest(event_digest: str) -> UnitRef:
    if (
        type(event_digest) is not str
        or len(event_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in event_digest)
    ):
        raise ValueError("event digest must be lowercase SHA-256")
    return UnitRef((_EVENT_REF_PREFIX + event_digest,))


def event_ref_digest(reference: UnitRef) -> str | None:
    if type(reference) is not UnitRef or len(reference.path) != 1:
        return None
    token = reference.path[0]
    if not token.startswith(_EVENT_REF_PREFIX):
        return None
    digest = token[len(_EVENT_REF_PREFIX) :]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return None
    return digest


def causal_event(
    *,
    authority_domain: str,
    generation: int,
    subject: UnitRoleValue,
    operation: str,
    phase: str,
    modality: TruthModality,
    causal_parents: tuple[UnitRef, ...] = (),
    reads: tuple[str, ...] = (),
    writes: tuple[str, ...] = (),
    evidence: tuple[UnitRoleValue, ...] = (),
    event_kind: str = EVENT_SCHEMA,
    physical_effect: bool = False,
    commutative_when_disjoint: bool = True,
    attributes: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    domain = unit_token(authority_domain, "event authority domain")
    if type(operation) is not str or not operation.strip():
        raise ValueError("event operation must be non-empty text")
    if type(phase) is not str or not phase.strip():
        raise ValueError("event phase must be non-empty text")
    operation = operation.strip()
    phase = phase.strip()
    event_kind = unit_token(event_kind, "event kind")
    if type(generation) is not int or generation < 0:
        raise ValueError("event generation must be a non-negative integer")
    modality = TruthModality(modality)
    if modality is TruthModality.AUTHORIZED and generation < 1:
        raise ValueError("authorized event generation must be positive")
    if type(physical_effect) is not bool or type(commutative_when_disjoint) is not bool:
        raise TypeError("event physical/commutativity flags must be boolean")
    if any(type(parent) is not UnitRef for parent in causal_parents):
        raise TypeError("event causal parents must be UnitRef values")
    parent_digests = tuple(event_ref_digest(parent) for parent in causal_parents)
    if any(digest is None for digest in parent_digests):
        raise ValueError("event causal parents must be content-addressed event refs")
    if len(parent_digests) != len(set(parent_digests)):
        raise ValueError("event causal parents must be unique")
    frozen_extra = freeze_json({} if attributes is None else dict(attributes))
    if not isinstance(frozen_extra, Mapping):
        raise TypeError("event attributes must be an object")

    read_set = _texts(reads, "event reads")
    write_set = _texts(writes, "event writes")
    payload = modal_attributes(
        modality,
        {
            "kind": event_kind,
            "authority_domain": domain,
            "generation": generation,
            "operation": operation,
            "phase": phase,
            "reads": read_set,
            "writes": write_set,
            "physical_effect": physical_effect,
            "commutative_when_disjoint": commutative_when_disjoint,
            "event_attributes": dict(frozen_extra),
        },
    )
    roles = [role("subject", subject)]
    if causal_parents:
        roles.append(role("causal-parent", *causal_parents))
    if evidence:
        roles.append(role("evidence", *evidence))
    schemas = (EVENT_SCHEMA,) if event_kind == EVENT_SCHEMA else (EVENT_SCHEMA, event_kind)
    provisional = NoetriumUnit(
        "event:provisional",
        schemas=schemas,
        attributes=payload,
        roles=tuple(roles),
    )
    return NoetriumUnit(
        _EVENT_REF_PREFIX + provisional.semantic_digest,
        schemas=schemas,
        attributes=payload,
        roles=tuple(roles),
    )


def is_event_unit(value: object) -> bool:
    return type(value) is NoetriumUnit and value.has_schema(EVENT_SCHEMA)


def require_event_unit(event: NoetriumUnit) -> NoetriumUnit:
    if not is_event_unit(event):
        raise TypeError("causal event projection requires system.event NoetriumUnit")
    modality = truth_modality(event)
    if modality is None:
        raise ValueError("event unit has no truth modality")
    generation = event.attribute("generation")
    if type(generation) is not int or generation < 0:
        raise ValueError("event unit has invalid generation")
    if modality is TruthModality.AUTHORIZED and generation < 1:
        raise ValueError("authorized event unit has non-positive generation")
    return event


def event_field(event: NoetriumUnit, name: str):
    require_event_unit(event)
    if name == "modality":
        return truth_modality(event)
    if name == "subject":
        values = event.role("subject")
        if len(values) != 1:
            raise ValueError("event subject must contain exactly one value")
        return values[0]
    if name == "causal_parents":
        return event.refs("causal-parent")
    if name == "evidence":
        return event.role("evidence")
    return event.attribute(name)


def event_conflict_keys(event: NoetriumUnit) -> frozenset[str]:
    require_event_unit(event)
    return frozenset((*event_field(event, "reads"), *event_field(event, "writes")))


def events_independent(left: NoetriumUnit, right: NoetriumUnit) -> bool:
    """Conservative trace-independence predicate."""

    require_event_unit(left)
    require_event_unit(right)
    if left.unit_digest == right.unit_digest:
        return False
    if event_field(left, "authority_domain") == event_field(right, "authority_domain"):
        return False
    left_reads = set(event_field(left, "reads"))
    left_writes = set(event_field(left, "writes"))
    right_reads = set(event_field(right, "reads"))
    right_writes = set(event_field(right, "writes"))
    if left_writes & (right_reads | right_writes):
        return False
    if right_writes & (left_reads | left_writes):
        return False
    if (
        event_field(left, "physical_effect")
        or event_field(right, "physical_effect")
    ) and not (
        event_field(left, "commutative_when_disjoint")
        and event_field(right, "commutative_when_disjoint")
    ):
        return False
    return True


def causal_topological_order(
    events: tuple[NoetriumUnit, ...],
) -> tuple[NoetriumUnit, ...]:
    """Deterministic Θ(V+E) order derived from the canonical DAG kernel."""

    by_digest: dict[str, NoetriumUnit] = {}
    edges: list[tuple[str, str]] = []
    for event in events:
        require_event_unit(event)
        if event.unit_digest in by_digest:
            raise ValueError("causal trace contains duplicate event identity")
        by_digest[event.unit_digest] = event

    for digest, event in by_digest.items():
        for reference in event_field(event, "causal_parents"):
            parent = event_ref_digest(reference)
            if parent is None or parent not in by_digest:
                raise ValueError(
                    "causal trace references an event outside the trace"
                )
            edges.append((parent, digest))

    order = deterministic_topological_order(
        tuple(by_digest),
        tuple(edges),
    )
    return tuple(by_digest[digest] for digest in order)


def merge_causal_traces(
    *traces: tuple[NoetriumUnit, ...],
) -> tuple[NoetriumUnit, ...]:
    """Content-addressed union of authority-partitioned traces.

    Identical Event Units deduplicate by digest. A digest collision with a
    different Unit fails closed. No synthetic ordering edge is introduced.
    """

    merged: dict[str, NoetriumUnit] = {}
    for trace in traces:
        for event in trace:
            require_event_unit(event)
            previous = merged.get(event.unit_digest)
            if previous is not None and previous != event:
                raise RuntimeError("causal Event digest collision")
            merged[event.unit_digest] = event
    return tuple(merged[digest] for digest in sorted(merged))


def reverse_causal_cone_from_traces(
    traces: tuple[tuple[NoetriumUnit, ...], ...],
    terminal: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    """Resolve a reverse causal cone across independent Authority journals."""

    merged = merge_causal_traces(*traces)
    return reverse_causal_cone(merged, terminal)


def reverse_causal_cone(
    events: tuple[NoetriumUnit, ...],
    terminal: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    """Return the exact reverse causal cone in O(|V_C|+|E_C|)."""

    require_event_unit(terminal)
    by_digest = {event.unit_digest: require_event_unit(event) for event in events}
    if terminal.unit_digest not in by_digest:
        raise ValueError("terminal event is outside the supplied trace")
    seen: set[str] = set()
    stack = [terminal.unit_digest]
    result: list[NoetriumUnit] = []
    while stack:
        digest = stack.pop()
        if digest in seen:
            continue
        seen.add(digest)
        event = by_digest[digest]
        result.append(event)
        for reference in event_field(event, "causal_parents"):
            parent = event_ref_digest(reference)
            if parent is None or parent not in by_digest:
                raise ValueError("causal trace references an event outside the trace")
            stack.append(parent)
    result.sort(key=lambda event: event.unit_digest)
    return tuple(result)


__all__ = [
    "EVENT_SCHEMA",
    "causal_event",
    "causal_topological_order",
    "event_conflict_keys",
    "event_field",
    "event_ref",
    "event_ref_from_digest",
    "event_ref_digest",
    "events_independent",
    "is_event_unit",
    "reverse_causal_cone_from_traces",
    "merge_causal_traces",
    "require_event_unit",
    "reverse_causal_cone",
]
