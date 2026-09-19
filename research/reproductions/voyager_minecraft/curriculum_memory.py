from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    MemoryConcern,
    MemoryProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import VOYAGER_AUDITED_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class VoyagerQAEntry:
    question: str
    answer: str
    ordinal: int
    entry_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question",
            _text(self.question, "Voyager QA question"),
        )
        object.__setattr__(
            self,
            "answer",
            _text(self.answer, "Voyager QA answer"),
        )
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("Voyager QA ordinal must be positive")
        object.__setattr__(
            self,
            "entry_digest",
            canonical_digest({
                "question": self.question,
                "answer": self.answer,
                "ordinal": self.ordinal,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "question": self.question,
            "answer": self.answer,
            "ordinal": self.ordinal,
            "entry_digest": self.entry_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "VoyagerQAEntry":
        if not isinstance(value, Mapping):
            raise TypeError("Voyager QA entry must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("Voyager QA entry must decode to an object")
        entry = cls(
            question=decoded.get("question"),
            answer=decoded.get("answer"),
            ordinal=decoded.get("ordinal"),
        )
        supplied = decoded.get("entry_digest")
        if supplied is not None and supplied != entry.entry_digest:
            raise ValueError("Voyager QA entry digest mismatch")
        return entry


@dataclass(frozen=True, slots=True)
class VoyagerQANearestRequest:
    question: str
    cached_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VoyagerQANearestResult:
    question: str | None
    distance: float | None
    receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.question is not None:
            object.__setattr__(
                self,
                "question",
                _text(self.question, "Voyager nearest cached question"),
            )
        if self.distance is not None:
            if (
                isinstance(self.distance, bool)
                or not isinstance(self.distance, (int, float))
                or float(self.distance) < 0.0
            ):
                raise ValueError("Voyager QA distance must be non-negative")
            object.__setattr__(self, "distance", float(self.distance))
        if (self.question is None) != (self.distance is None):
            raise ValueError(
                "Voyager QA nearest question and distance must co-occur"
            )
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "question": self.question,
                "distance": self.distance,
                "receipt": thaw_json(self.receipt),
            }),
        )


@runtime_checkable
class VoyagerQANearestPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def nearest(
        self,
        request: VoyagerQANearestRequest,
    ) -> VoyagerQANearestResult: ...


@dataclass(frozen=True, slots=True)
class VoyagerQAMemoryBinding:
    nearest: VoyagerQANearestPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.nearest, VoyagerQANearestPort):
            raise TypeError("Voyager QA memory requires nearest-neighbor port")
        digest = require_sha256(
            self.nearest.identity_digest,
            "Voyager QA nearest port identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "nearest_port_identity_digest": digest,
                "semantic_reuse_distance_threshold": 0.05,
            }),
        )


def voyager_qa_memory_initial_data() -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "semantic_reuse_distance_threshold": 0.05,
        "entries": (),
        "sequence": 0,
        "result": None,
    }


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("Voyager QA-memory payload must be an object")
    return decoded


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("Voyager QA-memory data must be an object")
    if decoded.get("source_commit") != VOYAGER_AUDITED_COMMIT:
        raise ValueError("Voyager QA-memory source identity drifted")
    return decoded


def _entries(value: object) -> tuple[VoyagerQAEntry, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError("Voyager QA entries must be a sequence")
    return tuple(VoyagerQAEntry.from_payload(row) for row in value)


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, VoyagerQAMemoryBinding):
        raise TypeError(
            "Voyager QA-memory dispatch requires VoyagerQAMemoryBinding"
        )
    data = _data(request)
    envelope = _payload(request)
    event = envelope.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("Voyager QA-memory requires event envelope")
    kind = _text(event.get("kind"), "Voyager QA-memory event kind")
    raw_payload = event.get("payload", {})
    if not isinstance(raw_payload, Mapping):
        raise TypeError("Voyager QA-memory event payload must be an object")
    payload = dict(thaw_json(raw_payload))
    entries = list(_entries(data.get("entries", ())))
    sequence = data.get("sequence", 0)
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Voyager QA-memory sequence is invalid")

    if kind == "voyager.qa.lookup":
        question = _text(payload.get("question"), "Voyager QA lookup question")
        allow_semantic = payload.get("allow_semantic", False)
        if type(allow_semantic) is not bool:
            raise TypeError("Voyager QA allow_semantic must be boolean")
        exact = next(
            (entry for entry in entries if entry.question == question),
            None,
        )
        if exact is not None:
            result = {
                "hit": True,
                "match_kind": "exact",
                "query_question": question,
                "matched_question": exact.question,
                "answer": exact.answer,
                "distance": 0.0,
                "entry_digest": exact.entry_digest,
            }
            return ProgramNodeResult(
                value=result,
                state_update={"result": result},
                events=({
                    "type": "voyager_qa_cache_hit",
                    "match_kind": "exact",
                    "entry_digest": exact.entry_digest,
                },),
            )

        if allow_semantic and entries:
            nearest = binding.nearest.nearest(
                VoyagerQANearestRequest(
                    question=question,
                    cached_questions=tuple(
                        entry.question for entry in entries
                    ),
                )
            )
            if not isinstance(nearest, VoyagerQANearestResult):
                raise TypeError(
                    "Voyager QA nearest port must return VoyagerQANearestResult"
                )
            if (
                nearest.question is not None
                and nearest.distance is not None
                and nearest.distance
                < data.get("semantic_reuse_distance_threshold", 0.05)
            ):
                matched = next(
                    (
                        entry
                        for entry in entries
                        if entry.question == nearest.question
                    ),
                    None,
                )
                if matched is None:
                    raise ValueError(
                        "Voyager QA nearest port returned unknown cached question"
                    )
                result = {
                    "hit": True,
                    "match_kind": "semantic",
                    "query_question": question,
                    "matched_question": matched.question,
                    "answer": matched.answer,
                    "distance": nearest.distance,
                    "entry_digest": matched.entry_digest,
                    "retrieval_receipt": thaw_json(nearest.receipt),
                    "retrieval_digest": nearest.result_digest,
                }
                return ProgramNodeResult(
                    value=result,
                    state_update={"result": result},
                    events=({
                        "type": "voyager_qa_cache_hit",
                        "match_kind": "semantic",
                        "entry_digest": matched.entry_digest,
                        "distance": nearest.distance,
                        "retrieval_digest": nearest.result_digest,
                    },),
                )

        result = {
            "hit": False,
            "match_kind": None,
            "query_question": question,
            "matched_question": None,
            "answer": None,
            "distance": None,
        }
        return ProgramNodeResult(
            value=result,
            state_update={"result": result},
            events=({
                "type": "voyager_qa_cache_miss",
                "query_digest": canonical_digest(question),
                "semantic_lookup": allow_semantic,
            },),
        )

    if kind == "voyager.qa.write":
        question = _text(payload.get("question"), "Voyager QA write question")
        answer = _text(payload.get("answer"), "Voyager QA write answer")
        if any(entry.question == question for entry in entries):
            raise ValueError(
                "paper-era Voyager QA cache refuses duplicate question writes"
            )
        entry = VoyagerQAEntry(
            question=question,
            answer=answer,
            ordinal=sequence + 1,
        )
        entries.append(entry)
        result = {
            "question": question,
            "answer": answer,
            "entry_digest": entry.entry_digest,
            "entry_count": len(entries),
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "entries": tuple(row.payload() for row in entries),
                "sequence": sequence + 1,
                "result": result,
            },
            events=({
                "type": "voyager_qa_cache_written",
                "entry_digest": entry.entry_digest,
                "entry_count": len(entries),
            },),
        )

    raise ValueError(f"unsupported Voyager QA-memory event: {kind}")


def build_voyager_qa_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="voyager.curriculum-qa-memory",
            version=VOYAGER_AUDITED_COMMIT[:12],
            state_schema="voyager.curriculum-qa-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "voyager.curriculum-qa-memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.INDEX.value,
                ),
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "semantic_reuse_distance_threshold": 0.05,
            },
            next_node="dispatch",
        )
        .build()
    )


VOYAGER_QA_MEMORY_PROGRAM = build_voyager_qa_memory_program()


def voyager_qa_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "voyager.curriculum-qa-memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "voyager.curriculum-qa-memory.dispatch",
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def voyager_qa_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="voyager.curriculum-qa-memory",
        program=VOYAGER_QA_MEMORY_PROGRAM,
        operations=voyager_qa_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": VOYAGER_AUDITED_COMMIT,
            "semantic_reuse_distance_threshold": 0.05,
        },
    )


__all__ = [
    "VOYAGER_QA_MEMORY_PROGRAM",
    "VoyagerQAEntry",
    "VoyagerQAMemoryBinding",
    "VoyagerQANearestPort",
    "VoyagerQANearestRequest",
    "VoyagerQANearestResult",
    "build_voyager_qa_memory_program",
    "voyager_qa_memory_host",
    "voyager_qa_memory_initial_data",
    "voyager_qa_memory_operations",
]
