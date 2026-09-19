"""Programmable Memory Machine semantics.

The platform owns the Machine ABI and durable facts. Memory algorithms are
ordinary Program rules/handlers: downstream research may replace write,
retrieval, trust, consolidation or retention semantics without adding a new
runner or changing the kernel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from .domains import MemoryConcern
from .program_host import ResearchProgramHost
from .program import (
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchProgram,
)
from .rule_program import (
    ProgramRule,
    ProgramRuleSet,
    RuleDispatchMode,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)


@dataclass(frozen=True, slots=True)
class MemoryPresetSpec:
    max_records: int = 2048
    recall_limit: int = 12
    generation_bonus: int = 2
    token_overlap_weight: int = 5

    def __post_init__(self) -> None:
        for name, value in (
            ("max_records", self.max_records),
            ("recall_limit", self.recall_limit),
            ("generation_bonus", self.generation_bonus),
            ("token_overlap_weight", self.token_overlap_weight),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"memory preset {name} must be a non-negative integer")
        if self.max_records < 1 or self.recall_limit < 1:
            raise ValueError("memory preset capacities must be positive")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "max_records": self.max_records,
            "recall_limit": self.recall_limit,
            "generation_bonus": self.generation_bonus,
            "token_overlap_weight": self.token_overlap_weight,
        })


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    record_id: str
    kind: str
    content: str
    generation: str
    state_digest: str
    tags: tuple[str, ...] = ()
    verified: bool = False
    ordinal: int = 0
    artifact_refs: tuple[str, ...] = ()
    metadata: JsonObject = field(default_factory=dict)
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("record_id", self.record_id),
            ("kind", self.kind),
            ("content", self.content),
            ("generation", self.generation),
            ("state_digest", self.state_digest),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"memory record {name} is required")
        if type(self.tags) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.tags
        ):
            raise TypeError("memory record tags must be a tuple of non-empty strings")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("memory record tags must be unique")
        if type(self.verified) is not bool:
            raise TypeError("memory record verified must be boolean")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("memory record ordinal must be non-negative")
        if type(self.artifact_refs) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.artifact_refs
        ):
            raise TypeError("memory record artifact_refs must be non-empty text")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("memory record metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        object.__setattr__(self, "record_digest", canonical_digest(self.as_payload(include_digest=False)))

    def as_payload(self, *, include_digest: bool = True) -> JsonObject:
        payload: JsonObject = {
            "record_id": self.record_id,
            "kind": self.kind,
            "content": self.content,
            "generation": self.generation,
            "state_digest": self.state_digest,
            "tags": self.tags,
            "verified": self.verified,
            "ordinal": self.ordinal,
            "artifact_refs": self.artifact_refs,
            "metadata": self.metadata,
        }
        if include_digest:
            payload["record_digest"] = self.record_digest
        return payload

    @classmethod
    def from_payload(cls, value: object) -> "MemoryRecord":
        if not isinstance(value, Mapping):
            raise TypeError("memory record payload must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("memory record payload must decode to an object")
        tags = decoded.get("tags", ())
        refs = decoded.get("artifact_refs", ())
        metadata = decoded.get("metadata", {})
        if not isinstance(tags, (tuple, list)):
            raise TypeError("memory record tags must be a sequence")
        if not isinstance(refs, (tuple, list)):
            raise TypeError("memory record artifact_refs must be a sequence")
        if not isinstance(metadata, dict):
            raise TypeError("memory record metadata must be an object")
        return cls(
            record_id=decoded.get("record_id"),
            kind=decoded.get("kind"),
            content=decoded.get("content"),
            generation=decoded.get("generation"),
            state_digest=decoded.get("state_digest"),
            tags=tuple(tags),
            verified=decoded.get("verified", False),
            ordinal=decoded.get("ordinal", 0),
            artifact_refs=tuple(refs),
            metadata=metadata,
        )


def memory_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule(
                "write",
                "memory.write",
                "memory.default.write",
                priority=100,
                semantic=MemoryConcern.WRITE.value,
            ),
            ProgramRule(
                "retrieve",
                "memory.retrieve",
                "memory.default.retrieve",
                priority=100,
                semantic=MemoryConcern.RETRIEVAL.value,
            ),
            ProgramRule(
                "verify",
                "memory.verify",
                "memory.default.verify",
                priority=100,
                semantic=MemoryConcern.TRUST.value,
            ),
            ProgramRule(
                "forget",
                "memory.forget",
                "memory.default.forget",
                priority=100,
                semantic=MemoryConcern.RETENTION.value,
            ),
            ProgramRule(
                "compact",
                "memory.compact",
                "memory.default.compact",
                priority=100,
                semantic=MemoryConcern.CONSOLIDATION.value,
            ),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_memory_program(
    *,
    program_id: str = "memory.default",
    version: str = "1",
    rules: ProgramRuleSet | None = None,
) -> ResearchProgram:
    selected = memory_rule_set() if rules is None else rules
    return compile_rule_program(
        program_id=program_id,
        kind=MachineKind.MEMORY,
        version=version,
        state_schema="memory.program.state.v1",
        rules=selected,
    )


def memory_initial_data(
    spec: MemoryPresetSpec = MemoryPresetSpec(),
) -> JsonObject:
    if not isinstance(spec, MemoryPresetSpec):
        raise TypeError("memory initial data requires MemoryPresetSpec")
    return {
        "preset_digest": spec.digest,
        "max_records": spec.max_records,
        "recall_limit": spec.recall_limit,
        "generation_bonus": spec.generation_bonus,
        "token_overlap_weight": spec.token_overlap_weight,
        "sequence_counter": 0,
        "records": (),
    }


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    if not isinstance(request.payload, Mapping):
        raise TypeError("memory event payload must be an object")
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("memory event payload must decode to an object")
    return value


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("memory program data must be an object")
    return value


def _records(data: dict[str, object]) -> list[MemoryRecord]:
    rows = data.get("records", ())
    if not isinstance(rows, (tuple, list)):
        raise TypeError("memory records must be a sequence")
    return [MemoryRecord.from_payload(row) for row in rows]


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_:-]+", value.lower())
        if len(token) > 1
    }


def default_memory_operations() -> ProgramHandlerRegistry:
    """Reference preset only; downstream papers may bind different operations."""

    operations = ProgramHandlerRegistry()

    def write(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        record_value = payload.get("record")
        if not isinstance(record_value, Mapping):
            raise TypeError("memory.write requires record object")
        candidate = MemoryRecord.from_payload(record_value)
        sequence = data.get("sequence_counter", 0)
        if type(sequence) is not int or sequence < 0:
            raise ValueError("memory sequence_counter is invalid")
        ordinal = candidate.ordinal if candidate.ordinal > 0 else sequence + 1
        record = MemoryRecord(
            candidate.record_id,
            candidate.kind,
            candidate.content,
            candidate.generation,
            candidate.state_digest,
            candidate.tags,
            candidate.verified,
            ordinal,
            candidate.artifact_refs,
            candidate.metadata,
        )
        rows = [row for row in _records(data) if row.record_id != record.record_id]
        rows.append(record)
        max_records = data.get("max_records")
        if type(max_records) is not int or max_records < 1:
            raise ValueError("memory max_records is invalid")
        evicted = rows[:-max_records] if len(rows) > max_records else []
        rows = rows[-max_records:]
        next_sequence = max(sequence + 1, record.ordinal)
        return ProgramNodeResult(
            value={
                "record_id": record.record_id,
                "record_digest": record.record_digest,
                "evicted_record_ids": tuple(row.record_id for row in evicted),
            },
            state_update={
                "sequence_counter": next_sequence,
                "records": tuple(row.as_payload() for row in rows),
            },
            events=({
                "type": "memory_record_written",
                "record_id": record.record_id,
                "record_digest": record.record_digest,
                "verified": record.verified,
                "evicted_record_ids": tuple(row.record_id for row in evicted),
            },),
            artifact_refs=record.artifact_refs,
        )

    def retrieve(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        query_text = payload.get("query_text", "")
        if type(query_text) is not str:
            raise TypeError("memory query_text must be text")
        generation = payload.get("generation")
        if generation is not None and (type(generation) is not str or not generation.strip()):
            raise ValueError("memory generation filter must be non-empty text")
        tags = payload.get("tags", ())
        if not isinstance(tags, (tuple, list)) or any(
            type(value) is not str or not value.strip() for value in tags
        ):
            raise TypeError("memory query tags must be a text sequence")
        require_verified = payload.get("require_verified", True)
        if type(require_verified) is not bool:
            raise TypeError("memory require_verified must be boolean")
        limit = payload.get("limit", data.get("recall_limit"))
        if type(limit) is not int or limit < 1:
            raise ValueError("memory retrieval limit must be positive")
        overlap_weight = data.get("token_overlap_weight", 5)
        generation_bonus = data.get("generation_bonus", 2)
        if type(overlap_weight) is not int or type(generation_bonus) is not int:
            raise TypeError("memory scoring weights must be integers")

        query = _tokens(query_text + " " + " ".join(tags))
        scored: list[tuple[int, int, MemoryRecord]] = []
        for index, record in enumerate(_records(data)):
            if require_verified and not record.verified:
                continue
            overlap = len(query & _tokens(record.content + " " + " ".join(record.tags)))
            score = overlap * overlap_weight
            if generation is not None and record.generation == generation:
                score += generation_bonus
            score += min(record.ordinal, 100) // 10
            if score > 0 or not query:
                scored.append((score, index, record))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2].record_id))
        selected = scored[:limit]
        rows = tuple(item[2] for item in selected)
        query_id = "memory-query:" + canonical_digest({
            "query_text": query_text,
            "generation": generation,
            "tags": tuple(tags),
            "require_verified": require_verified,
            "limit": limit,
            "record_digests": tuple(row.record_digest for row in rows),
        })
        context_text = "\n".join(f"[{row.kind}] {row.content}" for row in rows)
        artifact_refs = tuple(
            dict.fromkeys(ref for row in rows for ref in row.artifact_refs)
        )
        return ProgramNodeResult(
            value={
                "query_id": query_id,
                "context_text": context_text,
                "record_ids": tuple(row.record_id for row in rows),
                "record_digests": tuple(row.record_digest for row in rows),
                "scores": tuple(item[0] for item in selected),
                "artifact_refs": artifact_refs,
            },
            events=({
                "type": "memory_retrieved",
                "query_id": query_id,
                "record_ids": tuple(row.record_id for row in rows),
            },),
            artifact_refs=artifact_refs,
        )

    def verify(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        record_id = payload.get("record_id")
        verified = payload.get("verified")
        if type(record_id) is not str or not record_id.strip():
            raise ValueError("memory.verify requires record_id")
        if type(verified) is not bool:
            raise TypeError("memory.verify verified must be boolean")
        rows = _records(data)
        found = False
        updated: list[MemoryRecord] = []
        for row in rows:
            if row.record_id != record_id:
                updated.append(row)
                continue
            found = True
            updated.append(MemoryRecord(
                row.record_id,
                row.kind,
                row.content,
                row.generation,
                row.state_digest,
                row.tags,
                verified,
                row.ordinal,
                row.artifact_refs,
                row.metadata,
            ))
        if not found:
            raise KeyError(record_id)
        return ProgramNodeResult(
            value={"record_id": record_id, "verified": verified},
            state_update={"records": tuple(row.as_payload() for row in updated)},
            events=({
                "type": "memory_record_verification_changed",
                "record_id": record_id,
                "verified": verified,
            },),
        )

    def forget(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        record_ids = payload.get("record_ids")
        if isinstance(record_ids, str) or not isinstance(record_ids, (tuple, list)):
            raise TypeError("memory.forget record_ids must be a sequence")
        ids = tuple(record_ids)
        if any(type(value) is not str or not value.strip() for value in ids):
            raise ValueError("memory.forget record_ids must be non-empty text")
        if len(ids) != len(set(ids)):
            raise ValueError("memory.forget record_ids must be unique")
        remove = set(ids)
        rows = _records(data)
        retained = [row for row in rows if row.record_id not in remove]
        forgotten = tuple(row.record_id for row in rows if row.record_id in remove)
        return ProgramNodeResult(
            value={"forgotten_record_ids": forgotten},
            state_update={"records": tuple(row.as_payload() for row in retained)},
            events=({
                "type": "memory_records_forgotten",
                "record_ids": forgotten,
            },),
        )

    def compact(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        keep = payload.get("keep", data.get("max_records"))
        if type(keep) is not int or keep < 0:
            raise ValueError("memory.compact keep must be non-negative")
        rows = _records(data)
        removed = rows[:-keep] if keep and len(rows) > keep else ([] if keep else rows)
        retained = rows[-keep:] if keep else []
        return ProgramNodeResult(
            value={"removed_record_ids": tuple(row.record_id for row in removed)},
            state_update={"records": tuple(row.as_payload() for row in retained)},
            events=({
                "type": "memory_compacted",
                "removed_record_ids": tuple(row.record_id for row in removed),
                "retained_count": len(retained),
            },),
        )

    operations.register(
        "memory.default.write",
        write,
        implementation_digest=canonical_digest({
            "operation": "memory.default.write",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "memory.default.retrieve",
        retrieve,
        implementation_digest=canonical_digest({
            "operation": "memory.default.retrieve",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "memory.default.verify",
        verify,
        implementation_digest=canonical_digest({
            "operation": "memory.default.verify",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "memory.default.forget",
        forget,
        implementation_digest=canonical_digest({
            "operation": "memory.default.forget",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "memory.default.compact",
        compact,
        implementation_digest=canonical_digest({
            "operation": "memory.default.compact",
            "implementation_revision": 1,
        }),
    )
    return operations


def default_memory_handlers() -> ProgramHandlerRegistry:
    return build_rule_handlers(memory_rule_set(), default_memory_operations())


def default_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
    preset: MemoryPresetSpec = MemoryPresetSpec(),
) -> ResearchProgramHost:
    """Default MemoryProgram host; preset policy stays replaceable downstream."""
    if not isinstance(preset, MemoryPresetSpec):
        raise TypeError("memory host preset must be MemoryPresetSpec")
    program = compile_memory_program()
    return ResearchProgramHost(
        host_id="memory.default",
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        base_handlers=default_memory_handlers(),
        dependency_identity={
            "rule_set_digest": memory_rule_set().rule_set_digest,
            "preset_digest": preset.digest,
        },
    )


__all__ = [
    "MemoryPresetSpec",
    "MemoryRecord",
    "compile_memory_program",
    "default_memory_handlers",
    "default_memory_host",
    "default_memory_operations",
    "memory_initial_data",
    "memory_rule_set",
]
