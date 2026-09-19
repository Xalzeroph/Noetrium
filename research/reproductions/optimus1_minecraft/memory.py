from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
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

from .fidelity import OPTIMUS1_REFERENCE_FIDELITY
from .source import OPTIMUS1_PAPER_ERA_COMMIT


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"{field_name} must be non-empty")
    return result


def _object(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _rows(value: object, field_name: str) -> tuple[JsonObject, ...]:
    decoded = thaw_json(value)
    if isinstance(decoded, (str, bytes, bytearray)) or not isinstance(
        decoded, Sequence
    ):
        raise TypeError(f"{field_name} must be a sequence")
    rows: list[JsonObject] = []
    for row in decoded:
        if not isinstance(row, Mapping):
            raise TypeError(f"{field_name} rows must be objects")
        rows.append(_object(row, field_name))
    return tuple(rows)


def _task_key(value: object) -> str:
    return _text(value, "Optimus-1 task").replace(" ", "_").lower()


@runtime_checkable
class Optimus1RetrievalPolicyPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def best_match(
        self,
        query: str,
        choices: tuple[str, ...],
    ) -> str | None: ...

    def choose_reflection(
        self,
        *,
        task_key: str,
        environment: str,
        category: str,
        candidates: tuple[JsonObject, ...],
    ) -> int: ...


@runtime_checkable
class Optimus1KnowledgeGraphPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def compile(self, goal: str, number: int = 1) -> str: ...


@dataclass(frozen=True, slots=True)
class Optimus1MemoryBinding:
    retrieval: Optimus1RetrievalPolicyPort
    knowledge_graph: Optimus1KnowledgeGraphPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.retrieval, Optimus1RetrievalPolicyPort):
            raise TypeError("Optimus-1 requires retrieval policy binding")
        if not isinstance(self.knowledge_graph, Optimus1KnowledgeGraphPort):
            raise TypeError("Optimus-1 requires knowledge graph binding")
        retrieval_digest = require_sha256(
            self.retrieval.identity_digest,
            "Optimus-1 retrieval identity_digest",
        )
        graph_digest = require_sha256(
            self.knowledge_graph.identity_digest,
            "Optimus-1 knowledge graph identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
                    "retrieval_identity_digest": retrieval_digest,
                    "knowledge_graph_identity_digest": graph_digest,
                }
            ),
        )


def optimus1_memory_initial_data() -> JsonObject:
    return {
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "sequence": 0,
        "plans": (),
        "reflections": (),
        "replans": (),
        "result": None,
    }


def _event(request: ProgramNodeRequest) -> tuple[str, JsonObject]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("Optimus-1 memory payload must be an object")
    event = decoded.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("Optimus-1 memory requires event envelope")
    event = _object(event, "Optimus-1 memory event")
    kind = _text(event.get("kind"), "Optimus-1 memory event kind")
    payload = _object(
        event.get("payload", {}),
        "Optimus-1 memory event payload",
    )
    return kind, payload


def _data(request: ProgramNodeRequest) -> JsonObject:
    data = _object(request.data, "Optimus-1 memory state")
    if data.get("source_commit") != OPTIMUS1_PAPER_ERA_COMMIT:
        raise ValueError("Optimus-1 source identity drifted")
    return data


def _sequence(data: Mapping[str, object]) -> int:
    value = data.get("sequence", 0)
    if type(value) is not int or value < 0:
        raise ValueError("Optimus-1 memory sequence is invalid")
    return value + 1


def _write_plan(
    request: ProgramNodeRequest,
    data: JsonObject,
    payload: JsonObject,
) -> ProgramNodeResult:
    status = _text(payload.get("status"), "Optimus-1 plan status")
    if status not in {"success", "failed"}:
        raise ValueError("Optimus-1 plan status must be success or failed")
    task_key = _task_key(payload.get("task"))
    planning = payload.get("planning", ())
    if isinstance(planning, (str, bytes, bytearray)) or not isinstance(
        planning, Sequence
    ):
        raise TypeError("Optimus-1 planning must be a sequence")
    steps = payload.get("steps")
    if isinstance(steps, bool) or not isinstance(steps, (int, float)) or steps < 0:
        raise ValueError("Optimus-1 plan steps must be non-negative numeric")
    record: JsonObject = {
        "task_key": task_key,
        "task": _text(payload.get("task"), "Optimus-1 task"),
        "environment": _text(
            payload.get("environment", "none"),
            "Optimus-1 environment",
        ),
        "visual_info": _text(
            payload.get("visual_info", ""),
            "Optimus-1 visual_info",
            allow_empty=True,
        ),
        "goal": _text(payload.get("goal"), "Optimus-1 goal"),
        "planning": tuple(thaw_json(row) for row in planning),
        "status": status,
        "steps": float(steps),
        "video_artifact_ref": payload.get("video_artifact_ref"),
    }
    record["record_digest"] = canonical_digest(record)
    plans = (*_rows(data.get("plans", ()), "Optimus-1 plans"), record)
    result = {
        "kind": "plan",
        "status": status,
        "task_key": task_key,
        "record_digest": record["record_digest"],
        "plan_count": len(plans),
    }
    return ProgramNodeResult(
        value=result,
        state_update={
            "sequence": _sequence(data),
            "plans": plans,
            "result": result,
        },
        events=(
            {
                "type": "optimus1_plan_memory_written",
                "task_key": task_key,
                "status": status,
                "record_digest": record["record_digest"],
            },
        ),
    )


def _write_reflection(
    request: ProgramNodeRequest,
    data: JsonObject,
    payload: JsonObject,
) -> ProgramNodeResult:
    category = _text(
        payload.get("category"),
        "Optimus-1 reflection category",
    )
    if category not in OPTIMUS1_REFERENCE_FIDELITY.amep_reflection_labels:
        raise ValueError("Optimus-1 reflection category drifted")
    record: JsonObject = {
        "task_key": _task_key(payload.get("task")),
        "environment": _text(
            payload.get("environment"),
            "Optimus-1 reflection environment",
        ),
        "category": category,
        "before_artifact_ref": _text(
            payload.get("before_artifact_ref"),
            "Optimus-1 before artifact ref",
        ),
        "after_artifact_ref": _text(
            payload.get("after_artifact_ref"),
            "Optimus-1 after artifact ref",
        ),
    }
    record["record_digest"] = canonical_digest(record)
    reflections = (
        *_rows(data.get("reflections", ()), "Optimus-1 reflections"),
        record,
    )
    result = {
        "kind": "reflection",
        "category": category,
        "record_digest": record["record_digest"],
        "reflection_count": len(reflections),
    }
    return ProgramNodeResult(
        value=result,
        state_update={
            "sequence": _sequence(data),
            "reflections": reflections,
            "result": result,
        },
        artifact_refs=(
            record["before_artifact_ref"],
            record["after_artifact_ref"],
        ),
        events=(
            {
                "type": "optimus1_reflection_memory_written",
                "task_key": record["task_key"],
                "environment": record["environment"],
                "category": category,
                "record_digest": record["record_digest"],
            },
        ),
    )


def _write_replan(
    request: ProgramNodeRequest,
    data: JsonObject,
    payload: JsonObject,
) -> ProgramNodeResult:
    planning = payload.get("planning", ())
    if isinstance(planning, (str, bytes, bytearray)) or not isinstance(
        planning, Sequence
    ):
        raise TypeError("Optimus-1 replan planning must be a sequence")
    record: JsonObject = {
        "task_key": _task_key(payload.get("task")),
        "error_info": _text(
            payload.get("error_info"),
            "Optimus-1 replan error_info",
        ),
        "planning": tuple(thaw_json(row) for row in planning),
    }
    record["record_digest"] = canonical_digest(record)
    replans = (*_rows(data.get("replans", ()), "Optimus-1 replans"), record)
    result = {
        "kind": "replan",
        "record_digest": record["record_digest"],
        "replan_count": len(replans),
    }
    return ProgramNodeResult(
        value=result,
        state_update={
            "sequence": _sequence(data),
            "replans": replans,
            "result": result,
        },
        events=(
            {
                "type": "optimus1_replan_memory_written",
                "task_key": record["task_key"],
                "error_digest": canonical_digest(record["error_info"]),
                "record_digest": record["record_digest"],
            },
        ),
    )


def _retrieve_plan(
    data: JsonObject,
    payload: JsonObject,
    binding: Optimus1MemoryBinding,
) -> ProgramNodeResult:
    task_key = _task_key(payload.get("task"))
    success = tuple(
        row
        for row in _rows(data.get("plans", ()), "Optimus-1 plans")
        if row.get("status") == "success"
    )
    choices = tuple(dict.fromkeys(_task_key(row.get("task_key")) for row in success))
    best = binding.retrieval.best_match(task_key, choices) if choices else None
    if best is None:
        result = {
            "task_key": task_key,
            "found": False,
            "has_done": False,
            "record": None,
        }
    else:
        if best not in choices:
            raise ValueError("Optimus-1 retrieval selected unknown plan task")
        record = next(row for row in success if row.get("task_key") == best)
        result = {
            "task_key": task_key,
            "matched_task_key": best,
            "found": True,
            "has_done": best == task_key,
            "record": record,
        }
    return ProgramNodeResult(value=result, state_update={"result": result})


def _retrieve_reflection(
    data: JsonObject,
    payload: JsonObject,
    binding: Optimus1MemoryBinding,
) -> ProgramNodeResult:
    task_key = _task_key(payload.get("task"))
    environment = _text(
        payload.get("environment"),
        "Optimus-1 reflection query environment",
    )
    reflections = _rows(
        data.get("reflections", ()),
        "Optimus-1 reflections",
    )
    task_choices = tuple(
        dict.fromkeys(_task_key(row.get("task_key")) for row in reflections)
    )
    matched_task = (
        binding.retrieval.best_match(task_key, task_choices)
        if task_choices
        else None
    )
    if matched_task is None:
        result = {
            "task_key": task_key,
            "environment": environment,
            "found": False,
            "matched_task_key": None,
            "matched_environment": None,
            "examples": {},
        }
        return ProgramNodeResult(value=result, state_update={"result": result})
    if matched_task not in task_choices:
        raise ValueError("Optimus-1 reflection selected unknown task")

    task_rows = tuple(
        row for row in reflections if row.get("task_key") == matched_task
    )
    environment_choices = tuple(
        dict.fromkeys(
            _text(row.get("environment"), "Optimus-1 reflection environment")
            for row in task_rows
        )
    )
    matched_environment = binding.retrieval.best_match(
        environment,
        environment_choices,
    )
    if matched_environment not in environment_choices:
        raise ValueError("Optimus-1 reflection selected unknown environment")

    selected: dict[str, JsonObject | None] = {}
    artifact_refs: list[str] = []
    for category in OPTIMUS1_REFERENCE_FIDELITY.amep_reflection_labels:
        candidates = tuple(
            row
            for row in task_rows
            if row.get("environment") == matched_environment
            and row.get("category") == category
        )
        if not candidates:
            selected[category] = None
            continue
        index = binding.retrieval.choose_reflection(
            task_key=matched_task,
            environment=matched_environment,
            category=category,
            candidates=candidates,
        )
        if type(index) is not int or not 0 <= index < len(candidates):
            raise ValueError("Optimus-1 reflection selector index is invalid")
        row = candidates[index]
        selected[category] = row
        artifact_refs.extend(
            (
                _text(
                    row.get("before_artifact_ref"),
                    "Optimus-1 before artifact ref",
                ),
                _text(
                    row.get("after_artifact_ref"),
                    "Optimus-1 after artifact ref",
                ),
            )
        )
    result = {
        "task_key": task_key,
        "environment": environment,
        "found": any(value is not None for value in selected.values()),
        "matched_task_key": matched_task,
        "matched_environment": matched_environment,
        "examples": selected,
    }
    return ProgramNodeResult(
        value=result,
        state_update={"result": result},
        artifact_refs=tuple(dict.fromkeys(artifact_refs)),
    )


def _retrieve_replan(
    data: JsonObject,
    payload: JsonObject,
) -> ProgramNodeResult:
    task_key = _task_key(payload.get("task"))
    error_info = _text(
        payload.get("error_info"),
        "Optimus-1 replan query error_info",
    )
    match = next(
        (
            row
            for row in _rows(data.get("replans", ()), "Optimus-1 replans")
            if task_key in _task_key(row.get("task_key"))
            and row.get("error_info") == error_info
        ),
        None,
    )
    result = {
        "task_key": task_key,
        "error_info": error_info,
        "found": match is not None,
        "record": match,
    }
    return ProgramNodeResult(value=result, state_update={"result": result})


def _retrieve_graph(
    payload: JsonObject,
    binding: Optimus1MemoryBinding,
) -> ProgramNodeResult:
    goal = _text(payload.get("goal"), "Optimus-1 graph goal")
    number = payload.get("number", 1)
    if type(number) is not int or number < 1:
        raise ValueError("Optimus-1 graph retrieval number must be positive")
    normalized = goal.replace("logs", "log").replace(" ", "_")
    direct_mining = {
        "iron_ore",
        "log",
        "cobblestone",
        "redstone",
        "sand",
        "coal_ore",
    }
    graph = (
        "Just mine it!"
        if normalized in direct_mining
        else binding.knowledge_graph.compile(normalized, number)
    )
    result = {
        "goal": goal,
        "normalized_goal": normalized,
        "number": number,
        "graph": _text(
            graph,
            "Optimus-1 compiled knowledge graph",
            allow_empty=True,
        ),
        "knowledge_graph_identity_digest": binding.knowledge_graph.identity_digest,
    }
    return ProgramNodeResult(value=result, state_update={"result": result})


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, Optimus1MemoryBinding):
        raise TypeError("Optimus-1 memory requires Optimus1MemoryBinding")
    data = _data(request)
    kind, payload = _event(request)

    if kind == "optimus1.memory.write-plan":
        return _write_plan(request, data, payload)
    if kind == "optimus1.memory.write-reflection":
        return _write_reflection(request, data, payload)
    if kind == "optimus1.memory.write-replan":
        return _write_replan(request, data, payload)
    if kind == "optimus1.memory.retrieve-plan":
        return _retrieve_plan(data, payload, binding)
    if kind == "optimus1.memory.retrieve-reflection":
        return _retrieve_reflection(data, payload, binding)
    if kind == "optimus1.memory.retrieve-replan":
        return _retrieve_replan(data, payload)
    if kind == "optimus1.memory.retrieve-graph":
        return _retrieve_graph(payload, binding)
    if kind == "optimus1.memory.readout":
        result = {
            "plan_count": len(_rows(data.get("plans", ()), "Optimus-1 plans")),
            "reflection_count": len(
                _rows(data.get("reflections", ()), "Optimus-1 reflections")
            ),
            "replan_count": len(
                _rows(data.get("replans", ()), "Optimus-1 replans")
            ),
            "sequence": data.get("sequence", 0),
        }
        return ProgramNodeResult(value=result, state_update={"result": result})

    raise ValueError(f"unknown Optimus-1 memory event: {kind}")


def build_optimus1_memory_program() -> ResearchProgram:
    fidelity = OPTIMUS1_REFERENCE_FIDELITY
    return (
        MemoryProgramBuilder.create(
            program_id="optimus1.hybrid-multimodal-memory",
            version=OPTIMUS1_PAPER_ERA_COMMIT[:12],
            state_schema="optimus1.hybrid-multimodal-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "optimus1.memory.dispatch",
            configuration={
                "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.INDEX.value,
                    MemoryConcern.PROJECTION.value,
                    MemoryConcern.RETENTION.value,
                ),
                "hybrid_memory_components": ("HDKG", "AMEP"),
                "amep_components": (
                    "plan_memory",
                    "reflection_memory",
                    "replan_memory",
                ),
                "reflection_labels": fidelity.amep_reflection_labels,
                "plan_retrieval": fidelity.plan_retrieval,
                "reflection_retrieval": fidelity.reflection_retrieval,
            },
            next_node="dispatch",
        )
        .build()
    )


OPTIMUS1_MEMORY_PROGRAM = build_optimus1_memory_program()


def optimus1_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "optimus1.memory.dispatch",
            _dispatch,
            canonical_digest(
                {
                    "operation": "optimus1.memory.dispatch",
                    "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
                    "implementation_revision": 1,
                }
            ),
        ),
    )


def optimus1_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="optimus1.hybrid-multimodal-memory",
        program=OPTIMUS1_MEMORY_PROGRAM,
        operations=optimus1_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
            "memory_components": ("HDKG", "AMEP"),
        },
    )


__all__ = [
    "OPTIMUS1_MEMORY_PROGRAM",
    "Optimus1KnowledgeGraphPort",
    "Optimus1MemoryBinding",
    "Optimus1RetrievalPolicyPort",
    "build_optimus1_memory_program",
    "optimus1_memory_host",
    "optimus1_memory_initial_data",
    "optimus1_memory_operations",
]
