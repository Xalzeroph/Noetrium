from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest


_HEX = frozenset("0123456789abcdef")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def _require_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field)


def _require_sha256(value: object, field: str) -> str:
    text = _require_string(value, field)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ValueError(f"{field} must be SHA-256")
    return text


def _require_completed_task_ids(value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError("workload execution cut completed_task_ids must be a tuple")
    if any(type(item) is not str for item in value):
        raise TypeError("workload execution cut task ids must be strings")
    if any(not item.strip() for item in value):
        raise ValueError("workload execution cut task ids must be non-empty")
    if len(set(value)) != len(value):
        raise ValueError("workload execution cut task ids must be unique")
    return value


def _validate_execution_cut_fields(
    completed_task_ids: object, current_task_id: object, decision_cycle_id: object, status: object
) -> None:
    completed = _require_completed_task_ids(completed_task_ids)
    current = _require_optional_string(current_task_id, "current workload task id")
    _require_optional_string(decision_cycle_id, "workload decision cycle id")
    normalized_status = _require_string(status, "workload execution cut status")
    if current in completed:
        raise ValueError("current workload task cannot already be completed")
    if normalized_status not in {"after_task", "in_task", "closed"}:
        raise ValueError(f"unsupported workload execution cut status: {normalized_status}")


class WorkloadRestoreStateCertainty(StrEnum):
    UNCHANGED = "UNCHANGED"
    ROLLED_BACK = "ROLLED_BACK"
    UNKNOWN = "UNKNOWN"


class WorkloadCheckpointRestoreError(RuntimeError):
    """Restore failed with explicit post-failure state certainty."""

    def __init__(
        self,
        *,
        phase: str,
        component_id: str,
        primary: BaseException,
        state_certainty: WorkloadRestoreStateCertainty,
        rollback_errors: tuple[tuple[str, BaseException], ...] = (),
    ) -> None:
        message = (
            "workload checkpoint restore failed: "
            f"phase={phase} component={component_id} state={state_certainty.value}"
        )
        if rollback_errors:
            message += f" rollback_failures={len(rollback_errors)}"
        super().__init__(message)
        self.phase = phase
        self.component_id = component_id
        self.primary = primary
        self.state_certainty = state_certainty
        self.rollback_errors = rollback_errors


@dataclass(frozen=True, slots=True)
class WorkloadExecutionCut:
    """A resumable task-boundary cut shared by every workload adapter.

    A cut is deliberately a task boundary, not an inferred position from a
    result file.  The task ids, optional current task and status are persisted
    with the component snapshots so recovery cannot silently mix a method
    snapshot from one execution prefix with an environment snapshot from
    another prefix.
    """

    completed_task_ids: tuple[str, ...]
    current_task_id: str | None = None
    decision_cycle_id: str | None = None
    status: str = "after_task"

    def __post_init__(self) -> None:
        _validate_execution_cut_fields(
            self.completed_task_ids, self.current_task_id, self.decision_cycle_id, self.status
        )

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class WorkloadCheckpointComponentRef:
    component_id: str
    codec_id: str
    schema_version: str
    payload_sha256: str
    payload_size: int

    def __post_init__(self) -> None:
        _require_string(self.component_id, "workload checkpoint component_id")
        _require_string(self.codec_id, "workload checkpoint codec_id")
        _require_string(self.schema_version, "workload checkpoint schema_version")
        _require_sha256(self.payload_sha256, "workload checkpoint payload_sha256")
        if type(self.payload_size) is not int:
            raise TypeError("workload checkpoint component payload_size must be an integer")
        if self.payload_size < 0:
            raise ValueError("workload checkpoint component payload size cannot be negative")


@dataclass(frozen=True, slots=True)
class WorkloadCheckpointPayload:
    ref: WorkloadCheckpointComponentRef
    payload: bytes

    def __post_init__(self) -> None:
        if type(self.ref) is not WorkloadCheckpointComponentRef:
            raise TypeError("workload checkpoint payload ref must be WorkloadCheckpointComponentRef")
        if type(self.payload) is not bytes:
            raise TypeError("workload checkpoint payload must be bytes")
        if _sha256(self.payload) != self.ref.payload_sha256:
            raise ValueError(f"workload checkpoint payload digest mismatch: {self.ref.component_id}")
        if len(self.payload) != self.ref.payload_size:
            raise ValueError(f"workload checkpoint payload size mismatch: {self.ref.component_id}")


def _require_component_refs(value: object) -> tuple[WorkloadCheckpointComponentRef, ...]:
    if type(value) is not tuple:
        raise TypeError("workload checkpoint component_refs must be a tuple")
    if any(type(item) is not WorkloadCheckpointComponentRef for item in value):
        raise TypeError("workload checkpoint component_refs contain invalid values")
    ids = tuple(item.component_id for item in value)
    if len(ids) != len(set(ids)):
        raise ValueError("workload checkpoint component ids must be unique")
    return value


def _validate_manifest_fields(
    required: tuple[object, ...], execution_cut: object, execution_cut_digest: object, component_refs: object
) -> None:
    for index, value in enumerate(required):
        _require_string(value, f"workload checkpoint manifest identity[{index}]")
    if type(execution_cut) is not WorkloadExecutionCut:
        raise TypeError("workload checkpoint execution_cut must be WorkloadExecutionCut")
    digest = _require_sha256(execution_cut_digest, "workload checkpoint execution_cut_digest")
    if execution_cut.digest() != digest:
        raise ValueError("workload checkpoint execution cut digest mismatch")
    _require_component_refs(component_refs)


@dataclass(frozen=True, slots=True)
class WorkloadCheckpointManifest:
    checkpoint_id: str
    schema_version: str
    run_id: str
    study_id: str
    workload_id: str
    branch_id: str
    source_cut_id: str
    environment_generation: str
    method_generation: str
    task_manifest_digest: str
    checkpoint_compatibility_digest: str
    execution_cut: WorkloadExecutionCut
    execution_cut_digest: str
    component_refs: tuple[WorkloadCheckpointComponentRef, ...]

    def __post_init__(self) -> None:
        _validate_manifest_fields(
            (
                self.checkpoint_id, self.schema_version, self.run_id, self.study_id,
                self.workload_id, self.branch_id, self.source_cut_id,
                self.environment_generation, self.method_generation,
                self.task_manifest_digest, self.checkpoint_compatibility_digest, self.execution_cut_digest,
            ),
            self.execution_cut,
            self.execution_cut_digest,
            self.component_refs,
        )
        _require_sha256(
            self.checkpoint_compatibility_digest,
            "workload checkpoint checkpoint_compatibility_digest",
        )

    def digest(self) -> str:
        return canonical_digest(self)


def _require_payloads(value: object) -> tuple[WorkloadCheckpointPayload, ...]:
    if type(value) is not tuple:
        raise TypeError("workload checkpoint bundle payloads must be a tuple")
    if any(type(item) is not WorkloadCheckpointPayload for item in value):
        raise TypeError("workload checkpoint bundle payloads contain invalid values")
    ids = tuple(item.ref.component_id for item in value)
    if len(ids) != len(set(ids)):
        raise ValueError("workload checkpoint bundle payload component ids must be unique")
    return value


def _validate_bundle_fields(manifest: object, payloads: object) -> None:
    if type(manifest) is not WorkloadCheckpointManifest:
        raise TypeError("workload checkpoint bundle manifest is invalid")
    normalized = _require_payloads(payloads)
    expected = {item.component_id for item in manifest.component_refs}
    actual = {item.ref.component_id for item in normalized}
    if actual != expected:
        raise ValueError("workload checkpoint payload topology does not match manifest")


@dataclass(frozen=True, slots=True)
class WorkloadCheckpointBundle:
    manifest: WorkloadCheckpointManifest
    payloads: tuple[WorkloadCheckpointPayload, ...]

    def __post_init__(self) -> None:
        _validate_bundle_fields(self.manifest, self.payloads)


@runtime_checkable
class WorkloadCheckpointStore(Protocol):
    durability: str

    def publish(
        self,
        manifest: WorkloadCheckpointManifest,
        payloads: tuple[WorkloadCheckpointPayload, ...],
    ) -> WorkloadCheckpointManifest: ...

    def load(self, checkpoint_id: str) -> WorkloadCheckpointBundle: ...


@runtime_checkable
class WorkloadCheckpointComponentPort(Protocol):
    component_id: str
    codec_id: str
    schema_version: str

    def capture(self) -> bytes: ...

    def restore(self, payload: bytes) -> None: ...


@runtime_checkable
class WorkloadCheckpointBindingPort(Protocol):
    run_id: str
    study_id: str
    workload_id: str
    branch_id: str
    source_cut_id: str
    environment_generation: str
    method_generation: str
    task_manifest_digest: str
    checkpoint_compatibility_digest: str

    def checkpoint_components(self) -> tuple[WorkloadCheckpointComponentPort, ...]: ...


def build_workload_checkpoint_manifest(
    *,
    run_id: str,
    study_id: str,
    workload_id: str,
    branch_id: str,
    source_cut_id: str,
    environment_generation: str,
    method_generation: str,
    task_manifest_digest: str,
    checkpoint_compatibility_digest: str,
    execution_cut: WorkloadExecutionCut,
    component_refs: tuple[WorkloadCheckpointComponentRef, ...],
    schema_version: str = "3",
) -> WorkloadCheckpointManifest:
    identity = {
        "schema_version": schema_version,
        "run_id": run_id,
        "study_id": study_id,
        "workload_id": workload_id,
        "branch_id": branch_id,
        "source_cut_id": source_cut_id,
        "environment_generation": environment_generation,
        "method_generation": method_generation,
        "task_manifest_digest": task_manifest_digest,
        "checkpoint_compatibility_digest": checkpoint_compatibility_digest,
        "execution_cut": execution_cut,
        "component_refs": component_refs,
    }
    return WorkloadCheckpointManifest(
        checkpoint_id=f"workload-checkpoint:{canonical_digest(identity)}",
        schema_version=schema_version,
        run_id=run_id,
        study_id=study_id,
        workload_id=workload_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        environment_generation=environment_generation,
        method_generation=method_generation,
        task_manifest_digest=task_manifest_digest,
        checkpoint_compatibility_digest=checkpoint_compatibility_digest,
        execution_cut=execution_cut,
        execution_cut_digest=execution_cut.digest(),
        component_refs=component_refs,
    )


__all__ = [
    "WorkloadCheckpointBindingPort",
    "WorkloadCheckpointRestoreError",
    "WorkloadCheckpointBundle",
    "WorkloadCheckpointComponentPort",
    "WorkloadCheckpointComponentRef",
    "WorkloadCheckpointManifest",
    "WorkloadCheckpointPayload",
    "WorkloadCheckpointStore",
    "WorkloadExecutionCut",
    "WorkloadRestoreStateCertainty",
    "build_workload_checkpoint_manifest",
]
