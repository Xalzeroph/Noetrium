from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import uuid
from typing import Generic, TypeVar

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from .context import ExecutionContext
from .identity import ComponentIdentity

T = TypeVar("T")
R = TypeVar("R")


def new_operation_invocation_id(operation_id: str) -> str:
    if not operation_id.strip():
        raise ValueError("operation_id must be non-empty")
    return f"{operation_id}@{uuid.uuid4().hex}"


class OperationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class EffectClass(StrEnum):
    PURE = "pure"
    IDEMPOTENT = "idempotent"
    RECONCILABLE = "reconcilable"
    NON_IDEMPOTENT = "non_idempotent"


class EffectCertainty(StrEnum):
    NO_EFFECT = "no_effect"
    EFFECT_CONFIRMED = "effect_confirmed"
    EFFECT_REJECTED = "effect_rejected"
    EFFECT_POSSIBLE = "effect_possible"
    EFFECT_UNKNOWN = "effect_unknown"


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    effect_id: str
    request_digest: str
    effect_class: EffectClass
    certainty: EffectCertainty
    provider_instance_id: str | None = None
    verification_required: bool = False
    before_artifact: str | None = None
    after_artifact: str | None = None
    provider_receipt: str | None = None

    def __post_init__(self) -> None:
        if not self.effect_id.strip() or not self.request_digest.strip():
            raise ValueError("effect receipt identity fields must be non-empty")
        if not isinstance(self.effect_class, EffectClass):
            raise TypeError("effect_class must be EffectClass")
        if not isinstance(self.certainty, EffectCertainty):
            raise TypeError("certainty must be EffectCertainty")


@dataclass(frozen=True, slots=True)
class OperationRequest(Generic[T]):
    operation_id: str
    invocation_id: str
    operation_type: str
    context: ExecutionContext
    caller: ComponentIdentity
    target: ComponentIdentity
    payload: T
    payload_schema: str
    payload_digest: str
    deadline_at: float | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.operation_id.strip() or not self.invocation_id.strip() or not self.operation_type.strip():
            raise ValueError("operation request identity fields must be non-empty")
        if not self.payload_schema.strip() or not self.payload_digest.strip():
            raise ValueError("operation payload schema/digest must be non-empty")


@dataclass(frozen=True, slots=True)
class OperationAuxiliaryFailure:
    subsystem: str
    stage: str
    error_type: str
    error_digest: str
    message: str = field(default="", repr=False, compare=False, metadata={"transient": True})

    @classmethod
    def from_exception(cls, subsystem: str, stage: str, exc: BaseException) -> "OperationAuxiliaryFailure":
        descriptor = describe_exception(exc)
        return cls(
            subsystem=subsystem,
            stage=stage,
            error_type=descriptor.error_type,
            error_digest=descriptor.error_digest,
            message=descriptor.safe_message,
        )


@dataclass(frozen=True, slots=True)
class OperationResult(Generic[R]):
    operation_id: str
    invocation_id: str
    status: OperationStatus
    output: R | None = None
    output_digest: str | None = None
    artifacts: tuple[str, ...] = ()
    mutations: tuple[str, ...] = ()
    failure_id: str | None = None
    effect_receipts: tuple[EffectReceipt, ...] = ()
    diagnostics: dict[str, object] = field(default_factory=dict)
    auxiliary_failures: tuple[OperationAuxiliaryFailure, ...] = ()
    # Process-local debugging aid only. Never enters canonical digests or durable evidence.
    cause: BaseException | None = field(default=None, repr=False, compare=False, metadata={"transient": True})
