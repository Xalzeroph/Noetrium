from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.infrastructure.reliability.effect.api import EffectReconciliationDisposition, PreparedEffectHandle
from noetrium_platform.foundation.kernel.kernel import EffectClass, EffectReceipt, ExecutionContext, JsonObject, JsonValue, canonical_digest, freeze_json



@dataclass(frozen=True, slots=True)
class CapabilityProviderIdentity:
    provider_id: str
    implementation_version: str
    abi_version: str
    schema_version: str
    artifact_digest: str = ""

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "implementation_version", "abi_version", "schema_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"capability provider {field_name} must be canonical non-empty text")
        if not isinstance(self.artifact_digest, str):
            raise TypeError("capability provider artifact_digest must be text")
        if self.artifact_digest and (
            not self.artifact_digest.strip()
            or self.artifact_digest != self.artifact_digest.strip()
        ):
            raise ValueError("capability provider artifact_digest must be canonical text when provided")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str
    interface_version: str
    request_schema: str
    result_schema: str
    effect_class: EffectClass = EffectClass.PURE
    deterministic: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.capability_id,
            self.interface_version,
            self.request_schema,
            self.result_schema,
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("capability descriptor identity fields must be canonical non-empty text")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    capability_id: str
    payload: JsonValue
    context: ExecutionContext
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability request identity is required")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("capability request context must be an ExecutionContext")
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip()
        ):
            raise ValueError("capability request idempotency_key must be non-empty when provided")
        object.__setattr__(
            self, "payload", freeze_json(self.payload)
        )


def capability_effect_request_id(request: CapabilityRequest) -> str:
    if not isinstance(request.idempotency_key, str) or not request.idempotency_key.strip():
        raise ValueError("effectful capability request requires a stable idempotency_key")
    slot = canonical_digest({
        "capability_id": request.capability_id,
        "idempotency_key": request.idempotency_key,
    })
    return f"capability-effect:{request.capability_id}:{slot[:24]}"


def capability_request_digest(request: CapabilityRequest) -> str:
    """Stable semantic identity for one capability request; excludes trace/span only data."""
    context = request.context
    return canonical_digest({
        "capability_id": request.capability_id,
        "payload": request.payload,
        "idempotency_key": request.idempotency_key,
        "run_id": context.run_id,
        "study_id": context.study_id,
        "lifetime_id": context.lifetime_id,
        "task_id": context.task_id,
        "decision_cycle_id": context.decision_cycle_id,
        "checkpoint_id": context.checkpoint_id,
        "participant_generations": context.participant_generations,
    })


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    capability_id: str
    payload: JsonValue
    generation: str | None = None
    artifacts: tuple[str, ...] = ()
    diagnostics: JsonObject = field(default_factory=dict)
    effect: EffectReceipt | None = None
    provider_identity: CapabilityProviderIdentity | None = None
    request_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability result identity is required")
        if self.generation is not None and (
            not isinstance(self.generation, str) or not self.generation.strip()
        ):
            raise ValueError("capability result generation must be non-empty when provided")
        if not isinstance(self.artifacts, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.artifacts
        ):
            raise TypeError("capability result artifacts must be a tuple of non-empty strings")
        object.__setattr__(
            self, "payload", freeze_json(self.payload)
        )
        if not isinstance(self.diagnostics, Mapping):
            raise TypeError("capability result diagnostics must be a mapping")
        object.__setattr__(
            self, "diagnostics", freeze_json(self.diagnostics)
        )
        if self.provider_identity is not None and not isinstance(
            self.provider_identity, CapabilityProviderIdentity
        ):
            raise TypeError("capability result provider_identity must be typed")
        if self.request_digest is not None and (
            not isinstance(self.request_digest, str)
            or len(self.request_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.request_digest)
        ):
            raise ValueError("capability result request_digest must be lowercase SHA-256")

    def digest(self) -> str:
        return canonical_digest({
            "capability_id": self.capability_id,
            "payload": self.payload,
            "generation": self.generation,
            "artifacts": self.artifacts,
            "diagnostics": self.diagnostics,
            "effect": self.effect,
            "provider_identity": self.provider_identity,
            "request_digest": self.request_digest,
        })


@dataclass(frozen=True, slots=True)
class CapabilityEffectReconciliationResult:
    capability_id: str
    disposition: EffectReconciliationDisposition
    result: CapabilityResult | None
    diagnostics: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability reconciliation identity is required")
        if self.result is not None and not isinstance(self.result, CapabilityResult):
            raise TypeError("capability reconciliation result must be CapabilityResult")
        if not isinstance(self.diagnostics, Mapping):
            raise TypeError("capability reconciliation diagnostics must be a mapping")
        object.__setattr__(
            self, "diagnostics",
            freeze_json(self.diagnostics),
        )


@runtime_checkable
class DurablePreparedCapabilitySession(Protocol):
    """Optional crash-durable effect capability implemented by a provider session.

    The provider owns opaque recovery semantics.  Platform code owns only the WAL
    envelope and exact request/receipt correlation.
    """

    effect_recovery_durability: str

    def prepare_capability_effect(
        self, request: CapabilityRequest
    ) -> PreparedEffectHandle: ...

    def execute_prepared_capability(
        self, request: CapabilityRequest, handle: PreparedEffectHandle
    ) -> CapabilityResult: ...

    def reconcile_prepared_capability(
        self, handle: PreparedEffectHandle, context: ExecutionContext
    ) -> CapabilityEffectReconciliationResult: ...


@runtime_checkable
class CapabilityPort(Protocol):
    """The only external-world surface visible to a generic Agent.

    Implementations may route to environments, tools, APIs, simulators, remote
    services, or other capability providers.  The consumer never receives the
    provider object itself.
    """

    def describe(self, capability_id: str) -> CapabilityDescriptor: ...
    def invoke(self, request: CapabilityRequest) -> CapabilityResult: ...


@runtime_checkable
class CapabilityExportSession(Protocol):
    """Optional capability surface that any runtime participant session may export."""

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]: ...
    def invoke(self, request: CapabilityRequest) -> CapabilityResult: ...


@runtime_checkable
class CapabilityProviderSession(CapabilityExportSession, Protocol):
    def checkpoint(self) -> bytes: ...
    def restore(self, payload: bytes) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class CapabilityProviderImplementation(Protocol):
    """Capability implementation identity/behavior without session lifecycle authority."""
    @property
    def identity(self) -> CapabilityProviderIdentity: ...
