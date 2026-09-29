from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass, field
import math
from typing import Mapping, Protocol, runtime_checkable

from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope, ModelOperationEnvelope, ModelRequestEnvelope,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, JsonInput

from .contracts import ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute
from .qualification import QualifiedModelEndpointBinding
from .streaming import ModelStreamEvent


@dataclass(frozen=True, slots=True)
class OperationalModelEndpointReplica:
    """One exact live route admitted for non-claim operational dispatch.

    This contract freezes only transport identity and capacity. It carries no
    qualification certificate and therefore must never be interpreted as
    scientific model equivalence or claim eligibility.
    """

    route: ModelEndpointRoute
    capacity: int

    def __post_init__(self) -> None:
        if not isinstance(self.route, ModelEndpointRoute):
            raise TypeError("operational endpoint replica requires ModelEndpointRoute")
        if type(self.capacity) is not int or self.capacity <= 0:
            raise ValueError("operational endpoint replica capacity must be positive")

    @property
    def deployment_id(self) -> str:
        return self.route.deployment_id

    @property
    def deployment_generation(self) -> str:
        return self.route.deployment_generation

    @property
    def max_admitted_concurrency(self) -> int:
        return self.capacity


@dataclass(frozen=True, slots=True)
class ModelEndpointReplicaSet:
    """One frozen endpoint set; qualification is authority state, not another type."""

    members: tuple[OperationalModelEndpointReplica | QualifiedModelEndpointBinding, ...]
    authority_kind: str = field(init=False)
    replica_set_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.members) is not tuple or not self.members:
            raise ValueError("model endpoint replica set requires at least one member")
        operational = all(isinstance(x, OperationalModelEndpointReplica) for x in self.members)
        qualified = all(isinstance(x, QualifiedModelEndpointBinding) for x in self.members)
        if not (operational or qualified):
            raise TypeError("model endpoint replica set members must share one authority kind")
        ordered = tuple(sorted(self.members, key=lambda x: x.deployment_id))
        if len({x.deployment_id for x in ordered}) != len(ordered):
            raise ValueError("model endpoint replica deployments must be unique")
        authority_kind = "qualified" if qualified else "operational"
        if qualified:
            canonical = ordered[0]
            for binding in ordered[1:]:
                if binding.role != canonical.role:
                    raise ValueError("qualified endpoint replicas must bind the same role")
                if (
                    binding.capability_id,
                    binding.input_schema_id,
                    binding.output_schema_id,
                ) != (
                    canonical.capability_id,
                    canonical.input_schema_id,
                    canonical.output_schema_id,
                ):
                    raise ValueError("qualified endpoint replicas must bind the same capability protocol")
                if binding.prompt_generation != canonical.prompt_generation:
                    raise ValueError("qualified endpoint replicas must bind the same prompt generation")
                if binding.model != canonical.model:
                    raise ValueError("qualified endpoint replicas must bind the same immutable model")
                if binding.model_stack_digest != canonical.model_stack_digest:
                    raise ValueError("qualified endpoint replicas must bind the same model stack")
                if binding.tokenizer_sha256 != canonical.tokenizer_sha256:
                    raise ValueError("qualified endpoint replicas must bind the same tokenizer")
                if binding.chat_template_sha256 != canonical.chat_template_sha256:
                    raise ValueError("qualified endpoint replicas must bind the same chat template")
                if binding.verified_capabilities != canonical.verified_capabilities:
                    raise ValueError(
                        "qualified endpoint replicas must bind the same verified capabilities"
                    )
        object.__setattr__(self, "members", ordered)
        object.__setattr__(self, "authority_kind", authority_kind)
        object.__setattr__(self, "replica_set_digest", canonical_digest({
            "schema": "model-endpoint-replica-set.v1",
            "authority_kind": authority_kind,
            "members": ordered,
        }))

    @property
    def qualified(self) -> bool:
        return self.authority_kind == "qualified"

    @property
    def role(self) -> str | None:
        return self.members[0].role if self.qualified else None

    @property
    def prompt_generation(self) -> str | None:
        return self.members[0].prompt_generation if self.qualified else None


@dataclass(frozen=True, slots=True)
class ModelEndpointReplicaSelectionCandidate:
    deployment_id: str
    capacity: int
    in_flight: int
    completed: int
    failures: int
    selections: int
    consecutive_failures: int
    ewma_latency_seconds: float | None
    last_selected_sequence: int
    attempted_in_dispatch: bool = False
    prefix_affinity_score: float = 0.0
    prefix_affinity_depth: int = 0

    def __post_init__(self) -> None:
        if type(self.deployment_id) is not str or not self.deployment_id.strip():
            raise ValueError("model endpoint selection candidate deployment_id is required")
        if type(self.capacity) is not int or self.capacity <= 0:
            raise ValueError("model endpoint selection candidate capacity must be positive")
        for name in (
            "in_flight", "completed", "failures", "selections",
            "consecutive_failures", "last_selected_sequence",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"model endpoint selection candidate {name} must be non-negative")
        if self.ewma_latency_seconds is not None and self.ewma_latency_seconds < 0:
            raise ValueError("model endpoint selection candidate latency must be non-negative")
        if type(self.attempted_in_dispatch) is not bool:
            raise TypeError(
                "model endpoint selection candidate attempted_in_dispatch must be bool"
            )
        if (
            isinstance(self.prefix_affinity_score, bool)
            or not isinstance(self.prefix_affinity_score, (int, float))
            or not math.isfinite(float(self.prefix_affinity_score))
            or not 0.0 <= float(self.prefix_affinity_score) <= 1.0
        ):
            raise ValueError(
                "model endpoint selection candidate prefix_affinity_score must be finite in [0, 1]"
            )
        if type(self.prefix_affinity_depth) is not int or self.prefix_affinity_depth < 0:
            raise ValueError(
                "model endpoint selection candidate prefix_affinity_depth must be non-negative"
            )


@runtime_checkable
class ModelEndpointReplicaSelectionPolicyPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def select(
        self,
        candidates: tuple[ModelEndpointReplicaSelectionCandidate, ...],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ModelEndpointReplicaSnapshot:
    deployment_id: str
    deployment_generation: str
    capacity: int
    in_flight: int
    completed: int
    failures: int
    selections: int
    consecutive_failures: int
    ewma_latency_seconds: float | None
    cooling_down: bool
    request_rejections: int = 0
    adaptive_limit: int | None = None
    adaptive_min_limit: int | None = None
    adaptive_max_limit: int | None = None
    adaptive_scale_up_suspended: bool = False
    adaptive_window_policy_digest: str | None = None
    adaptive_window_history: tuple[tuple[int, int, int, str, float], ...] = ()
    prefix_affinity_entries: int = 0
    prefix_affinity_selections: int = 0


@dataclass(frozen=True, slots=True)
class ModelEndpointPoolSnapshot:
    replica_set_digest: str
    selection_policy_digest: str
    selection_sequence: int
    replicas: tuple[ModelEndpointReplicaSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ModelEndpointDispatchAttempt:
    attempt_number: int
    deployment_id: str
    selection_sequence: int
    elapsed_seconds: float
    outcome: str
    failure_kind: str | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    wait_before_next_seconds: float = 0.0
    attempt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.attempt_number) is not int or self.attempt_number <= 0:
            raise ValueError("model endpoint attempt_number must be positive")
        if type(self.deployment_id) is not str or not self.deployment_id.strip():
            raise ValueError("model endpoint attempt deployment_id is required")
        if type(self.selection_sequence) is not int or self.selection_sequence <= 0:
            raise ValueError("model endpoint attempt selection_sequence must be positive")
        for name in ("elapsed_seconds", "wait_before_next_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"model endpoint attempt {name} must be finite and non-negative")
        if self.outcome not in {"completed", "request_rejected", "replica_failed"}:
            raise ValueError("model endpoint attempt outcome is invalid")
        if self.failure_kind is not None and (
            type(self.failure_kind) is not str or not self.failure_kind.strip()
        ):
            raise ValueError("model endpoint attempt failure_kind must be text or None")
        if type(self.retryable) is not bool:
            raise TypeError("model endpoint attempt retryable must be bool")
        if self.retry_after_seconds is not None and (
            isinstance(self.retry_after_seconds, bool)
            or not isinstance(self.retry_after_seconds, (int, float))
            or not math.isfinite(float(self.retry_after_seconds))
            or float(self.retry_after_seconds) < 0
        ):
            raise ValueError("model endpoint attempt retry_after_seconds must be finite and non-negative")
        object.__setattr__(
            self,
            "attempt_digest",
            canonical_digest({
                "schema":"noetrium.model-endpoint-dispatch-attempt.v1",
                "attempt_number":self.attempt_number,
                "deployment_id":self.deployment_id,
                "selection_sequence":self.selection_sequence,
                "elapsed_seconds":float(self.elapsed_seconds),
                "outcome":self.outcome,
                "failure_kind":self.failure_kind,
                "retryable":self.retryable,
                "retry_after_seconds":self.retry_after_seconds,
                "wait_before_next_seconds":float(self.wait_before_next_seconds),
            }),
        )


@dataclass(frozen=True, slots=True)
class ModelEndpointDispatchResult:
    request: ModelEndpointRequest
    response: ModelEndpointResponse
    replica_set_digest: str
    selection_policy_digest: str
    selection_sequence: int
    attempts: tuple[ModelEndpointDispatchAttempt, ...] = ()
    retry_policy_digest: str | None = None
    dispatch_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.response.deployment_id != self.request.deployment_id:
            raise ValueError("model endpoint dispatch response deployment drift")
        for name in ("replica_set_digest", "selection_policy_digest"):
            value = getattr(self, name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError(f"model endpoint dispatch {name} must be lowercase SHA-256")
        if type(self.attempts) is not tuple or any(
            not isinstance(attempt, ModelEndpointDispatchAttempt)
            for attempt in self.attempts
        ):
            raise TypeError("model endpoint dispatch attempts must be typed")
        if self.attempts:
            if self.attempts[-1].outcome != "completed":
                raise ValueError("successful model endpoint dispatch must end with completed attempt")
            if self.attempts[-1].selection_sequence != self.selection_sequence:
                raise ValueError("model endpoint dispatch final selection sequence drift")
        if self.retry_policy_digest is not None and (
            type(self.retry_policy_digest) is not str
            or len(self.retry_policy_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.retry_policy_digest)
        ):
            raise ValueError("model endpoint retry_policy_digest must be lowercase SHA-256")
        object.__setattr__(
            self,
            "dispatch_digest",
            canonical_digest(
                {
                    "request_digest": self.request.digest(),
                    "response_digest": self.response.response_digest,
                    "replica_set_digest": self.replica_set_digest,
                    "selection_policy_digest": self.selection_policy_digest,
                    "selection_sequence": self.selection_sequence,
                    "attempt_digests": tuple(
                        attempt.attempt_digest for attempt in self.attempts
                    ),
                    "retry_policy_digest": self.retry_policy_digest,
                }
            ),
        )


class ModelEndpointReplicaBindingPort(Protocol):
    def replica_set_for(
        self,
        *,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        prompt_generation: str | None = None,
    ) -> ModelEndpointReplicaSet: ...


@runtime_checkable
class ModelEndpointDispatchPoolPort(Protocol):
    """Minimal dispatch contract shared by operational and qualified pools."""

    def complete(
        self,
        request: ModelEndpointEnvelope,
        body: Mapping[str, JsonInput],
    ) -> ModelEndpointDispatchResult: ...

    def stream(
        self,
        request: ModelRequestEnvelope,
        body: Mapping[str, JsonInput],
        on_event: Callable[[ModelStreamEvent], None],
        *,
        stream_idle_timeout_s: float = 30.0,
    ) -> ModelEndpointDispatchResult: ...

    def snapshot(self) -> ModelEndpointPoolSnapshot: ...


class AdaptiveModelEndpointPoolPort(Protocol):
    @property
    def replica_set(self) -> ModelEndpointReplicaSet: ...

    def complete(
        self,
        request: ModelEndpointEnvelope,
        body: Mapping[str, JsonInput],
    ) -> ModelEndpointDispatchResult: ...

    def stream(
        self,
        request: ModelRequestEnvelope,
        body: Mapping[str, JsonInput],
        on_event: Callable[[ModelStreamEvent], None],
        *,
        stream_idle_timeout_s: float = 30.0,
    ) -> ModelEndpointDispatchResult: ...

    def snapshot(self) -> ModelEndpointPoolSnapshot: ...


__all__ = [
    "AdaptiveModelEndpointPoolPort",
    "ModelEndpointDispatchPoolPort",
    "ModelEndpointDispatchAttempt",
    "ModelEndpointDispatchResult",
    "ModelEndpointPoolSnapshot",
    "ModelEndpointReplicaSelectionCandidate",
    "ModelEndpointReplicaSelectionPolicyPort",
    "ModelEndpointReplicaSnapshot",
    "OperationalModelEndpointReplica",
    "ModelEndpointReplicaSet",
    "ModelEndpointReplicaBindingPort",
]
