from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, require_sha256


@dataclass(frozen=True, slots=True)
class MethodIdentity:
    method_id: str
    implementation_version: str
    abi_version: str
    schema_version: str
    artifact_digest: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.method_id, self.implementation_version, self.abi_version, self.schema_version)):
            raise ValueError("method identity fields must be non-empty text")
        if self.artifact_digest is not None:
            require_sha256(self.artifact_digest, "method artifact_digest")


@dataclass(frozen=True, slots=True)
class MethodProgramIdentity:
    """Exact implementation/configuration identity for one downstream scientific program."""

    implementation: MethodIdentity
    configuration_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.implementation, MethodIdentity):
            raise TypeError("method program implementation must be a MethodIdentity")
        if self.configuration_digest is not None:
            require_sha256(self.configuration_digest, "method program configuration_digest")

    def digest(self) -> str:
        return canonical_digest({"implementation": self.implementation, "configuration_digest": self.configuration_digest})


class MethodProgramIdentityMismatch(RuntimeError):
    """A hosted method program does not match the frozen Participant identity."""


@dataclass(frozen=True, slots=True)
class MethodSnapshot:
    method_id: str
    implementation_version: str
    schema_version: str
    method_runtime_binding_digest: str
    session_id: str
    payload_sha256: str
    opaque_payload: bytes


@dataclass(frozen=True, slots=True)
class RecallRequest:
    intent: str
    context: ExecutionContext
    limit: int = 8


@dataclass(frozen=True, slots=True)
class RecallResult:
    context_text: str
    method_generation: str
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MethodTaskOutcome:
    """Typed task outcome exposed to a method at the completion boundary.

    Workload/environment implementations may own richer receipts; method
    participants receive this explicit semantic projection rather than an
    opaque or mapping-shaped compatibility payload.
    """

    task_id: str
    family: str
    lineage_id: str
    success: bool
    utility: float
    steps: int
    failure_reason: str = ""
    memory_queries: int = 0

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.family.strip() or not self.lineage_id.strip():
            raise ValueError("method task outcome identity fields must be non-empty")
        if not isinstance(self.success, bool):
            raise TypeError("method task outcome success must be boolean")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.steps, self.memory_queries)
        ):
            raise ValueError("method task outcome counts must be non-negative integers")
        if not isinstance(self.failure_reason, str):
            raise TypeError("method task outcome failure_reason must be text")
        if not math.isfinite(float(self.utility)):
            raise ValueError("method task outcome utility must be finite")


@dataclass(frozen=True, slots=True)
class MethodTaskCompletionReceipt:
    completion_key: str
    method_generation: str | None = None
    artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.completion_key.strip():
            raise ValueError("completion_key must be non-empty")


@runtime_checkable
class IdempotentTaskCompletionSession(Protocol):
    """Optional capability required by crash-durable cross-component recovery."""

    task_completion_idempotency: str
    def task_completion_key(self, context: ExecutionContext) -> str: ...


@runtime_checkable
class TaskCompletionReconciliationSession(Protocol):
    """Optional stronger capability for COMMIT_ONLY crash recovery.

    The implementation may reconcile local session state from its own authoritative
    method state, but it must never execute a new task completion.  ``None`` means
    the method cannot prove that the completion key was committed.
    """

    def reconcile_task_completion(
        self, completion_key: str, context: ExecutionContext
    ) -> MethodTaskCompletionReceipt | None: ...


@runtime_checkable
class MethodSession(Protocol):
    def recall(self, request: RecallRequest) -> RecallResult: ...
    def ingest(self, evidence: JsonValue, context: ExecutionContext) -> None: ...
    def task_completed(self, result: JsonValue, context: ExecutionContext) -> MethodTaskCompletionReceipt | None: ...
    def checkpoint(self) -> MethodSnapshot: ...
    def restore(self, snapshot: MethodSnapshot) -> None: ...
    def diagnostics(self) -> Mapping[str, JsonValue]: ...
    def close(self) -> None: ...
