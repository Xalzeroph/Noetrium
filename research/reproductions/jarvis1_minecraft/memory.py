from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
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

from .source import JARVIS1_PUBLIC_EXECUTABLE_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _object(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise TypeError(f"{field_name} must be a sequence")
    rows = tuple(_text(item, field_name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must be unique")
    return rows


@dataclass(frozen=True, slots=True)
class Jarvis1MemoryPlanStep:
    goal: JsonObject
    skill_type: str
    text: str
    step_digest: str = field(init=False)

    def __post_init__(self) -> None:
        goal = _object(self.goal, "JARVIS-1 memory plan goal")
        if not goal:
            raise ValueError("JARVIS-1 memory plan goal must not be empty")
        for key, value in goal.items():
            _text(key, "JARVIS-1 memory goal item")
            if type(value) is not int or value < 1:
                raise ValueError(
                    "JARVIS-1 memory goal quantities must be positive integers"
                )
        object.__setattr__(self, "goal", freeze_json(goal))
        object.__setattr__(
            self,
            "skill_type",
            _text(self.skill_type, "JARVIS-1 memory skill_type"),
        )
        object.__setattr__(
            self,
            "text",
            _text(self.text, "JARVIS-1 memory plan text"),
        )
        object.__setattr__(
            self,
            "step_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        payload: JsonObject = {
            "goal": thaw_json(self.goal),
            "type": self.skill_type,
            "text": self.text,
        }
        if include_digest:
            payload["step_digest"] = self.step_digest
        return payload

    @classmethod
    def from_payload(cls, value: object) -> "Jarvis1MemoryPlanStep":
        row = _object(value, "JARVIS-1 memory plan step")
        step = cls(
            goal=_object(row.get("goal"), "JARVIS-1 memory plan goal"),
            skill_type=_text(
                row.get("type"),
                "JARVIS-1 memory plan type",
            ),
            text=_text(row.get("text"), "JARVIS-1 memory plan text"),
        )
        supplied = row.get("step_digest")
        if supplied is not None and require_sha256(
            supplied,
            "JARVIS-1 memory plan step_digest",
        ) != step.step_digest:
            raise ValueError("JARVIS-1 memory plan step digest mismatch")
        return step


@dataclass(frozen=True, slots=True)
class Jarvis1MemoryRecord:
    task_id: str
    timestamp: str
    status: str
    image_name: str | None
    init_inventory: JsonObject
    plan: tuple[Jarvis1MemoryPlanStep, ...]
    state_artifact_refs: tuple[str, ...] = ()
    action_artifact_refs: tuple[str, ...] = ()
    source_lane: str = "public-fixed-memory"
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "task_id",
            _text(self.task_id, "JARVIS-1 memory task_id"),
        )
        object.__setattr__(
            self,
            "timestamp",
            _text(self.timestamp, "JARVIS-1 memory timestamp"),
        )
        object.__setattr__(
            self,
            "status",
            _text(self.status, "JARVIS-1 memory status"),
        )
        if self.image_name is not None:
            object.__setattr__(
                self,
                "image_name",
                _text(self.image_name, "JARVIS-1 memory image_name"),
            )
        inventory = _object(
            self.init_inventory,
            "JARVIS-1 memory init_inventory",
        )
        for key, value in inventory.items():
            _text(key, "JARVIS-1 inventory item")
            if type(value) is not int or value < 0:
                raise ValueError(
                    "JARVIS-1 inventory quantities must be non-negative integers"
                )
        object.__setattr__(self, "init_inventory", freeze_json(inventory))
        if type(self.plan) is not tuple or any(
            not isinstance(item, Jarvis1MemoryPlanStep)
            for item in self.plan
        ):
            raise TypeError(
                "JARVIS-1 memory plan must be Jarvis1MemoryPlanStep tuple"
            )
        object.__setattr__(
            self,
            "state_artifact_refs",
            _text_tuple(
                self.state_artifact_refs,
                "JARVIS-1 state artifact refs",
            ),
        )
        object.__setattr__(
            self,
            "action_artifact_refs",
            _text_tuple(
                self.action_artifact_refs,
                "JARVIS-1 action artifact refs",
            ),
        )
        object.__setattr__(
            self,
            "source_lane",
            _text(self.source_lane, "JARVIS-1 memory source_lane"),
        )
        object.__setattr__(
            self,
            "record_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    @property
    def artifact_refs(self) -> tuple[str, ...]:
        return (
            *self.state_artifact_refs,
            *self.action_artifact_refs,
        )

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        payload: JsonObject = {
            "task_id": self.task_id,
            "time": self.timestamp,
            "status": self.status,
            "image": self.image_name,
            "init_inventory": thaw_json(self.init_inventory),
            "plan": tuple(item.payload() for item in self.plan),
            "state_artifact_refs": self.state_artifact_refs,
            "action_artifact_refs": self.action_artifact_refs,
            "source_lane": self.source_lane,
        }
        if include_digest:
            payload["record_digest"] = self.record_digest
        return payload

    @classmethod
    def from_payload(cls, value: object) -> "Jarvis1MemoryRecord":
        row = _object(value, "JARVIS-1 memory record")
        plan_value = row.get("plan", ())
        if isinstance(plan_value, (str, bytes, bytearray)) or not isinstance(
            plan_value, Sequence
        ):
            raise TypeError("JARVIS-1 memory plan must be a sequence")
        image = row.get("image")
        if image is not None and type(image) is not str:
            raise TypeError("JARVIS-1 memory image must be text or None")
        record = cls(
            task_id=_text(row.get("task_id"), "JARVIS-1 memory task_id"),
            timestamp=_text(row.get("time"), "JARVIS-1 memory time"),
            status=_text(row.get("status"), "JARVIS-1 memory status"),
            image_name=image,
            init_inventory=_object(
                row.get("init_inventory", {}),
                "JARVIS-1 memory init_inventory",
            ),
            plan=tuple(
                Jarvis1MemoryPlanStep.from_payload(item)
                for item in plan_value
            ),
            state_artifact_refs=_text_tuple(
                row.get("state_artifact_refs", ()),
                "JARVIS-1 state artifact refs",
            ),
            action_artifact_refs=_text_tuple(
                row.get("action_artifact_refs", ()),
                "JARVIS-1 action artifact refs",
            ),
            source_lane=_text(
                row.get("source_lane", "public-fixed-memory"),
                "JARVIS-1 memory source_lane",
            ),
        )
        supplied = row.get("record_digest")
        if supplied is not None and require_sha256(
            supplied,
            "JARVIS-1 memory record_digest",
        ) != record.record_digest:
            raise ValueError("JARVIS-1 memory record digest mismatch")
        return record


@dataclass(frozen=True, slots=True)
class Jarvis1MultimodalMemoryQuery:
    instruction: str
    visual_artifact_refs: tuple[str, ...] = ()
    inventory: JsonObject = field(default_factory=dict)
    query_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instruction",
            _text(self.instruction, "JARVIS-1 memory instruction"),
        )
        object.__setattr__(
            self,
            "visual_artifact_refs",
            _text_tuple(
                self.visual_artifact_refs,
                "JARVIS-1 visual artifact refs",
            ),
        )
        object.__setattr__(
            self,
            "inventory",
            freeze_json(
                _object(self.inventory, "JARVIS-1 memory query inventory")
            ),
        )
        object.__setattr__(
            self,
            "query_digest",
            canonical_digest({
                "instruction": self.instruction,
                "visual_artifact_refs": self.visual_artifact_refs,
                "inventory": thaw_json(self.inventory),
            }),
        )


@dataclass(frozen=True, slots=True)
class Jarvis1MemoryCandidate:
    record: Jarvis1MemoryRecord
    score: float
    candidate_receipt: JsonValue = None
    candidate_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.record, Jarvis1MemoryRecord):
            raise TypeError("JARVIS-1 candidate requires memory record")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(float(self.score))
        ):
            raise ValueError("JARVIS-1 candidate score must be finite numeric")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(
            self,
            "candidate_receipt",
            freeze_json(self.candidate_receipt),
        )
        object.__setattr__(
            self,
            "candidate_digest",
            canonical_digest({
                "record_digest": self.record.record_digest,
                "score": self.score,
                "candidate_receipt": thaw_json(self.candidate_receipt),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "record": self.record.payload(),
            "score": self.score,
            "candidate_receipt": thaw_json(self.candidate_receipt),
            "candidate_digest": self.candidate_digest,
        }


@dataclass(frozen=True, slots=True)
class Jarvis1MemoryRetrievalResult:
    query_digest: str
    candidates: tuple[Jarvis1MemoryCandidate, ...]
    retrieval_receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query_digest",
            require_sha256(
                self.query_digest,
                "JARVIS-1 retrieval query_digest",
            ),
        )
        if type(self.candidates) is not tuple or any(
            not isinstance(item, Jarvis1MemoryCandidate)
            for item in self.candidates
        ):
            raise TypeError(
                "JARVIS-1 retrieval candidates must be typed tuple"
            )
        object.__setattr__(
            self,
            "retrieval_receipt",
            freeze_json(self.retrieval_receipt),
        )
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "query_digest": self.query_digest,
                "candidate_digests": tuple(
                    item.candidate_digest for item in self.candidates
                ),
                "retrieval_receipt": thaw_json(self.retrieval_receipt),
            }),
        )


@runtime_checkable
class Jarvis1FixedMemoryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def lookup(self, task_id: str) -> Jarvis1MemoryRecord | None: ...


@runtime_checkable
class Jarvis1MultimodalRetrieverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def retrieve(
        self,
        query: Jarvis1MultimodalMemoryQuery,
    ) -> Jarvis1MemoryRetrievalResult: ...


@dataclass(frozen=True, slots=True)
class Jarvis1MemoryBinding:
    fixed_memory: Jarvis1FixedMemoryPort
    multimodal_retriever: Jarvis1MultimodalRetrieverPort | None = None
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.fixed_memory, Jarvis1FixedMemoryPort):
            raise TypeError(
                "JARVIS-1 memory binding requires fixed-memory port"
            )
        fixed_digest = require_sha256(
            self.fixed_memory.identity_digest,
            "JARVIS-1 fixed-memory identity_digest",
        )
        retrieval_digest = None
        if self.multimodal_retriever is not None:
            if not isinstance(
                self.multimodal_retriever,
                Jarvis1MultimodalRetrieverPort,
            ):
                raise TypeError(
                    "JARVIS-1 multimodal retriever must satisfy port"
                )
            retrieval_digest = require_sha256(
                self.multimodal_retriever.identity_digest,
                "JARVIS-1 retriever identity_digest",
            )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "public_executable_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
                "fixed_memory_identity_digest": fixed_digest,
                "multimodal_retriever_identity_digest": retrieval_digest,
            }),
        )


def jarvis1_memory_initial_data() -> JsonObject:
    return {
        "public_executable_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
        "sequence": 0,
        "result": None,
    }


def _event(request: ProgramNodeRequest) -> tuple[str, JsonObject]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("JARVIS-1 memory payload must be object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("JARVIS-1 memory requires event envelope")
    event = thaw_json(event)
    if not isinstance(event, dict):
        raise TypeError("JARVIS-1 memory event must decode to object")
    kind = _text(event.get("kind"), "JARVIS-1 memory event kind")
    payload = _object(
        event.get("payload", {}),
        "JARVIS-1 memory event payload",
    )
    return kind, payload


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, Jarvis1MemoryBinding):
        raise TypeError(
            "JARVIS-1 memory dispatch requires Jarvis1MemoryBinding"
        )
    if (
        request.data.get("public_executable_commit")
        != JARVIS1_PUBLIC_EXECUTABLE_COMMIT
    ):
        raise ValueError("JARVIS-1 public executable identity drifted")
    kind, payload = _event(request)
    sequence = request.data.get("sequence", 0)
    if type(sequence) is not int or sequence < 0:
        raise ValueError("JARVIS-1 memory sequence is invalid")
    sequence += 1

    artifact_refs: tuple[str, ...] = ()
    if kind == "jarvis1.memory.lookup-exact":
        task_id = _text(payload.get("task_id"), "JARVIS-1 task_id")
        record = binding.fixed_memory.lookup(task_id)
        if record is not None and not isinstance(
            record,
            Jarvis1MemoryRecord,
        ):
            raise TypeError(
                "JARVIS-1 fixed-memory lookup returned invalid record"
            )
        result: JsonObject = {
            "mode": "official-fixed-memory",
            "task_id": task_id,
            "found": record is not None,
            "record": None if record is None else record.payload(),
            "record_digest": (
                None if record is None else record.record_digest
            ),
        }
        if record is not None:
            artifact_refs = record.artifact_refs

    elif kind == "jarvis1.memory.retrieve-multimodal":
        if binding.multimodal_retriever is None:
            raise RuntimeError(
                "JARVIS-1 paper multimodal retrieval requires an explicit "
                "retriever binding; the public repository did not release it"
            )
        query = Jarvis1MultimodalMemoryQuery(
            instruction=_text(
                payload.get("instruction"),
                "JARVIS-1 retrieval instruction",
            ),
            visual_artifact_refs=_text_tuple(
                payload.get("visual_artifact_refs", ()),
                "JARVIS-1 visual artifact refs",
            ),
            inventory=_object(
                payload.get("inventory", {}),
                "JARVIS-1 retrieval inventory",
            ),
        )
        retrieval = binding.multimodal_retriever.retrieve(query)
        if not isinstance(retrieval, Jarvis1MemoryRetrievalResult):
            raise TypeError(
                "JARVIS-1 retriever must return Jarvis1MemoryRetrievalResult"
            )
        if retrieval.query_digest != query.query_digest:
            raise ValueError(
                "JARVIS-1 retrieval result query identity drifted"
            )
        artifact_refs = tuple(
            dict.fromkeys(
                ref
                for candidate in retrieval.candidates
                for ref in candidate.record.artifact_refs
            )
        )
        result = {
            "mode": "paper-semantic-multimodal",
            "query_digest": query.query_digest,
            "candidates": tuple(
                candidate.payload()
                for candidate in retrieval.candidates
            ),
            "retrieval_receipt": thaw_json(
                retrieval.retrieval_receipt
            ),
            "retrieval_result_digest": retrieval.result_digest,
            "retriever_identity_digest": (
                binding.multimodal_retriever.identity_digest
            ),
        }

    else:
        raise ValueError(f"unsupported JARVIS-1 memory event: {kind}")

    operation_digest = canonical_digest({
        "kind": kind,
        "sequence": sequence,
        "payload": payload,
        "result": result,
        "binding_digest": binding.binding_digest,
    })
    result = {
        **result,
        "sequence": sequence,
        "operation_digest": operation_digest,
    }
    return ProgramNodeResult(
        value=result,
        state_update={
            "sequence": sequence,
            "result": result,
        },
        events=({
            "type": "jarvis1_memory_operation",
            "kind": kind,
            "sequence": sequence,
            "operation_digest": operation_digest,
        },),
        artifact_refs=artifact_refs,
    )


def build_jarvis1_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="jarvis1.multimodal-memory",
            version=JARVIS1_PUBLIC_EXECUTABLE_COMMIT[:12],
            state_schema="jarvis1.multimodal-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "jarvis1.memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.INDEX.value,
                ),
                "public_source_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
                "public_mode": "fixed-task-keyed-memory",
                "paper_mode": "multimodal-retrieval-explicit-binding",
                "unreleased_public_components": (
                    "state-action-sequences",
                    "multimodal-descriptor",
                    "multimodal-retrieval",
                    "online-learning",
                ),
            },
            next_node="dispatch",
        )
        .build()
    )


JARVIS1_MEMORY_PROGRAM = build_jarvis1_memory_program()


def jarvis1_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "jarvis1.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "jarvis1.memory.dispatch",
                "public_source_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def jarvis1_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="jarvis1.multimodal-memory",
        program=JARVIS1_MEMORY_PROGRAM,
        operations=jarvis1_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "public_source_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
            "memory_semantics": canonical_digest({
                "fixed_memory": "task-keyed-exact-lookup",
                "paper_retrieval": "explicit-unreleased-policy-binding",
                "implementation_revision": 1,
            }),
        },
    )


__all__ = [
    "JARVIS1_MEMORY_PROGRAM",
    "Jarvis1FixedMemoryPort",
    "Jarvis1MemoryBinding",
    "Jarvis1MemoryCandidate",
    "Jarvis1MemoryPlanStep",
    "Jarvis1MemoryRecord",
    "Jarvis1MemoryRetrievalResult",
    "Jarvis1MultimodalMemoryQuery",
    "Jarvis1MultimodalRetrieverPort",
    "build_jarvis1_memory_program",
    "jarvis1_memory_host",
    "jarvis1_memory_initial_data",
    "jarvis1_memory_operations",
]
