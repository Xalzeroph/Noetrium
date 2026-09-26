from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, TypeAlias

JsonValue: TypeAlias = Any
JsonObject: TypeAlias = Mapping[str, Any]
MethodCall: TypeAlias = Any

@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    value: JsonValue = None
    state_update: Mapping[str, Any] = field(default_factory=dict)


_SHA256_RE = re.compile(r"[0-9a-f]{64}\\Z")


def _normalize(value: object, active: set[int]) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TypeError("non-finite floats are forbidden")
        return value
    if isinstance(value, Enum):
        return _normalize(value.value, active)
    if isinstance(value, bytes):
        return {"$bytes_sha256": hashlib.sha256(value).hexdigest(), "$bytes_size": len(value)}
    if isinstance(value, Path):
        return str(value)
    recursive = isinstance(value, (Mapping, list, tuple, set, frozenset)) or (
        is_dataclass(value) and not isinstance(value, type)
    )
    identity = id(value)
    if recursive:
        if identity in active:
            raise TypeError("cyclic canonical payload is forbidden")
        active.add(identity)
    try:
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: _normalize(getattr(value, field.name), active)
                for field in fields(value)
                if not field.metadata.get("transient", False)
            }
        if isinstance(value, Mapping):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("canonical mappings require string keys")
            return {key: _normalize(item, active) for key, item in value.items()}
        if isinstance(value, (set, frozenset)):
            rows=[_normalize(item, active) for item in value]
            return sorted(rows, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        if isinstance(value, (tuple, list)):
            return [_normalize(item, active) for item in value]
        raise TypeError(f"unsupported canonical payload type: {type(value).__name__}")
    finally:
        if recursive:
            active.remove(identity)


def canonical_digest(value: object) -> str:
    payload=json.dumps(_normalize(value, set()), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require_sha256(value: str, field: str = "sha256") -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be canonical lowercase SHA-256")
    return value


def freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise TypeError("non-finite floats are forbidden")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported {type(value).__name__} in frozen JSON")


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def method_event(kind: str, payload: Any = None) -> dict[str, Any]:
    return {"kind": kind, "payload": payload}


__all__ = [
    "JsonObject",
    "JsonValue",
    "MethodCall",
    "canonical_digest",
    "freeze_json",
    "method_event",
    "require_sha256",
    "thaw_json",
]


_METHOD_SPEC_ATTR = "__noetrium_method_spec__"


def method_configurer(
    *,
    method_id: str,
    entrypoint: str,
    version: str = "1",
    semantic_contract: str = "research.method.v1",
    configuration: Mapping[str, Any] | None = None,
    execution: str = "effect_recorded",
    evidence: tuple[str, ...] = (),
    metrics: tuple[str, ...] = (),
    artifacts: tuple[str, ...] = (),
    state_schema: str = "json",
    input_schema: str = "json",
    output_schema: str = "json",
):
    document = {
        "method_id": method_id,
        "entrypoint": entrypoint,
        "version": version,
        "semantic_contract": semantic_contract,
        "configuration": {} if configuration is None else dict(configuration),
        "execution": execution,
        "evidence": tuple(evidence),
        "metrics": tuple(metrics),
        "artifacts": tuple(artifacts),
        "state_schema": state_schema,
        "input_schema": input_schema,
        "output_schema": output_schema,
    }
    document["spec_digest"] = canonical_digest({
        "schema": "noetrium.reproduction-method-spec.v1",
        **document,
    })

    def decorate(configure):
        if not callable(configure):
            raise TypeError("method_configurer can decorate only callables")
        setattr(configure, _METHOD_SPEC_ATTR, freeze_json(document))
        return configure

    return decorate


def method_configurer_metadata(configure: object) -> Mapping[str, Any] | None:
    value = getattr(configure, _METHOD_SPEC_ATTR, None)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("method configurer metadata must be mapping")
    return value


def agent_phase(
    phase_id: str,
    agent_id: str,
    instruction: str,
    max_visits: int = 1,
) -> dict[str, Any]:
    return {
        "phase_id": phase_id,
        "agent_id": agent_id,
        "instruction": instruction,
        "max_visits": max_visits,
    }


def phase_view(instruction: str):
    def view(call):
        return {
            "instruction": instruction,
            "input": call.input_value,
            "previous": call.previous_value,
            "state": call.state,
        }
    return view


def phase_return(method_id: str, phase_ids: tuple[str, ...]):
    def handler(call):
        return call.transition(value={
            "method_id": method_id,
            "phase_ids": phase_ids,
            "result": call.previous_value,
        })
    return handler


def phase_cycle(first_phase_id: str, max_cycles: int):
    def handler(call):
        previous_count = call.state.get("__agent_cycle_count", 0)
        if type(previous_count) is not int or previous_count < 0:
            raise ValueError("agent cycle count must be a non-negative integer")
        completed = previous_count + 1
        return call.transition(
            value={
                "completed_cycles": completed,
                "last_result": call.previous_value,
            },
            state_update={"__agent_cycle_count": completed},
            next_node="return" if completed >= max_cycles else first_phase_id,
        )
    return handler

_STUDY_SPEC_ATTR = "__noetrium_study_spec__"
_BENCHMARK_CUT_ATTR = "__noetrium_benchmark_cut_requirements__"


def study_factory(benchmark_parameter: str):
    """Mark one plain-Python Study-spec factory for repository discovery."""

    if type(benchmark_parameter) is not str or not benchmark_parameter.strip():
        raise ValueError("study benchmark parameter must be non-empty")
    parameter = benchmark_parameter.strip()

    def decorate(factory):
        if not callable(factory):
            raise TypeError("study_factory can decorate only callables")
        setattr(
            factory,
            _STUDY_SPEC_ATTR,
            MappingProxyType({"benchmark_parameter": parameter}),
        )
        return factory

    return decorate


def requires_benchmark_cut(
    benchmark_id_or_factory,
    revision_id: str | None = None,
    *,
    split_ids: tuple[str, ...] = (),
    cut_digest: str | None = None,
):
    """Attach exact benchmark-cut metadata without importing Experimentation types."""

    if callable(benchmark_id_or_factory) and revision_id is None:
        return benchmark_id_or_factory

    benchmark_id = benchmark_id_or_factory
    if type(benchmark_id) is not str or not benchmark_id.strip():
        raise ValueError("benchmark cut benchmark_id must be non-empty")
    if type(revision_id) is not str or not revision_id.strip():
        raise ValueError("benchmark cut revision_id must be non-empty")
    if type(split_ids) is not tuple or any(
        type(row) is not str or not row.strip() for row in split_ids
    ):
        raise TypeError("benchmark cut split_ids must be a text tuple")
    if len(split_ids) != len(set(split_ids)):
        raise ValueError("benchmark cut split_ids must be unique")
    if cut_digest is not None:
        require_sha256(cut_digest, "benchmark cut digest")

    document = MappingProxyType(
        {
            "benchmark_id": benchmark_id.strip(),
            "revision_id": revision_id.strip(),
            "required_split_ids": tuple(sorted(split_ids)),
            "cut_digest": cut_digest,
        }
    )

    def decorate(factory):
        if not callable(factory):
            raise TypeError("benchmark cut requirement can decorate only callables")
        existing = getattr(factory, _BENCHMARK_CUT_ATTR, ())
        if type(existing) is not tuple or any(
            not isinstance(row, Mapping) for row in existing
        ):
            raise TypeError("benchmark cut metadata must be mapping tuple")
        if any(row.get("benchmark_id") == document["benchmark_id"] for row in existing):
            raise ValueError(
                f"duplicate benchmark cut requirement: {document['benchmark_id']!r}"
            )
        ordered = tuple(
            sorted(
                (*existing, document),
                key=lambda row: (
                    str(row["benchmark_id"]),
                    canonical_digest(row),
                ),
            )
        )
        setattr(factory, _BENCHMARK_CUT_ATTR, ordered)
        return factory

    return decorate


def study_protocol(protocol_id: str, configuration_digest: str) -> dict[str, Any]:
    if type(protocol_id) is not str or not protocol_id.strip():
        raise ValueError("study protocol_id must be non-empty")
    require_sha256(configuration_digest, "study protocol configuration_digest")
    return {
        "protocol_id": protocol_id.strip(),
        "configuration_digest": configuration_digest,
    }


def study_participant(
    *,
    role: str,
    kind: str,
    implementation: str,
    treatment: str,
    capabilities: tuple[str, ...] = (),
    configurations: tuple[str, ...] = (),
    depends_on: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "role": role,
        "kind": kind,
        "implementation": implementation,
        "treatment": treatment,
        "capabilities": tuple(capabilities),
        "configurations": tuple(configurations),
        "depends_on": tuple(depends_on),
    }


def study_model(
    requirement: str,
    *,
    prompt: str | None = None,
    usage: str = "execution",
    required: bool = True,
    max_bindings: int | None = 1,
) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "prompt": prompt,
        "usage": usage,
        "required": required,
        "max_bindings": max_bindings,
    }


def measurement(
    *,
    measurement_id: str,
    schema_id: str,
    value_kind: str,
    unit: str | None = None,
    description: str = "",
    semantic_kind: str = "measurement",
    scale: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    return {
        "measurement_id": measurement_id,
        "schema_id": schema_id,
        "value_kind": value_kind,
        "unit": unit,
        "description": description,
        "semantic_kind": semantic_kind,
        "scale": scale,
        "domain": domain,
    }


def scalar_measurement(
    measurement_id: str,
    *,
    schema_id: str,
    unit: str | None = None,
    description: str = "",
    semantic_kind: str = "measurement",
    scale: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    return measurement(
        measurement_id=measurement_id,
        schema_id=schema_id,
        value_kind="scalar",
        unit=unit,
        description=description,
        semantic_kind=semantic_kind,
        scale=scale,
        domain=domain,
    )


def trial_budget(
    budget_id: str,
    *,
    max_steps: int | None = None,
    max_seconds: float | None = None,
    max_tokens: int | None = None,
    resource_budget_digest: str | None = None,
    max_turns: int | None = None,
    max_messages: int | None = None,
    max_model_calls: int | None = None,
    max_working_seconds: float | None = None,
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    return {
        "budget_id": budget_id,
        "max_steps": max_steps,
        "max_seconds": max_seconds,
        "max_tokens": max_tokens,
        "resource_budget_digest": resource_budget_digest,
        "max_turns": max_turns,
        "max_messages": max_messages,
        "max_model_calls": max_model_calls,
        "max_working_seconds": max_working_seconds,
        "max_cost_usd": max_cost_usd,
    }


def assignment_workload(task_ids: tuple[str, ...]) -> dict[str, Any]:
    return {"task_ids": tuple(task_ids)}


def study_concurrency_isolated(
    *,
    max_parallel_repetitions: int,
    max_parallel_assignments: int,
    repetition_timeout_seconds: float,
    cpu_isolation: str = "worker",
    gpu_isolation: str = "provider-admission",
    environment_isolation: str = "per-assignment",
    model_admission_policy: str = "runtime-hierarchical-v1",
    scheduler_policy: str = "deterministic-priority-fair-v1",
) -> dict[str, Any]:
    return {
        "max_parallel_repetitions": max_parallel_repetitions,
        "parallel_assignments": True,
        "cpu_isolation": cpu_isolation,
        "gpu_isolation": gpu_isolation,
        "environment_isolation": environment_isolation,
        "model_admission_policy": model_admission_policy,
        "scheduler_policy": scheduler_policy,
        "repetition_timeout_seconds": repetition_timeout_seconds,
        "max_parallel_assignments": max_parallel_assignments,
    }


def study_spec(**values: Any) -> dict[str, Any]:
    """Return one plain Study document; Experimentation owns typed materialization."""

    return dict(values)


__all__ = [
    "AgentLoopResult",
    "JsonObject",
    "JsonValue",
    "MethodCall",
    "agent_phase",
    "assignment_workload",
    "canonical_digest",
    "freeze_json",
    "measurement",
    "method_configurer",
    "method_configurer_metadata",
    "method_event",
    "phase_cycle",
    "phase_return",
    "phase_view",
    "require_sha256",
    "requires_benchmark_cut",
    "scalar_measurement",
    "study_concurrency_isolated",
    "study_factory",
    "study_model",
    "study_participant",
    "study_protocol",
    "study_spec",
    "thaw_json",
    "trial_budget",
]
