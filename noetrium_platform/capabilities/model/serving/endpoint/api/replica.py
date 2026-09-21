from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.foundation.kernel.kernel import canonical_digest, JsonInput

from .contracts import ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute
from .qualification import QualifiedModelEndpointBinding


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
class OperationalModelEndpointReplicaSet:
    """Frozen route set for substitute/non-claim endpoint dispatch."""

    replicas: tuple[OperationalModelEndpointReplica, ...]
    replica_set_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.replicas) is not tuple or not self.replicas:
            raise ValueError("operational endpoint replica set requires at least one replica")
        if any(not isinstance(item, OperationalModelEndpointReplica) for item in self.replicas):
            raise TypeError("operational endpoint replica set contains invalid replica")
        ordered = tuple(sorted(self.replicas, key=lambda item: item.deployment_id))
        if len({item.deployment_id for item in ordered}) != len(ordered):
            raise ValueError("operational endpoint replica deployments must be unique")
        object.__setattr__(self, "replicas", ordered)
        object.__setattr__(self, "replica_set_digest", canonical_digest({
            "schema": "operational-model-endpoint-replica-set.v1",
            "replicas": tuple({
                "route": item.route,
                "capacity": item.capacity,
            } for item in ordered),
        }))


@dataclass(frozen=True, slots=True)
class QualifiedModelEndpointReplicaSet:
    """Operationally interchangeable replicas of one exact scientific model binding."""

    bindings: tuple[QualifiedModelEndpointBinding, ...]
    replica_set_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.bindings) is not tuple or not self.bindings:
            raise ValueError("qualified endpoint replica set requires at least one binding")
        ordered = tuple(sorted(self.bindings, key=lambda item: item.deployment_id))
        if len({item.deployment_id for item in ordered}) != len(ordered):
            raise ValueError("qualified endpoint replica deployments must be unique")
        canonical = ordered[0]
        for binding in ordered[1:]:
            if binding.role != canonical.role:
                raise ValueError("qualified endpoint replicas must bind the same role")
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
        object.__setattr__(self, "bindings", ordered)
        object.__setattr__(
            self,
            "replica_set_digest",
            canonical_digest(
                {
                    "role": canonical.role,
                    "prompt_generation": canonical.prompt_generation,
                    "model": canonical.model,
                    "model_stack_digest": canonical.model_stack_digest,
                    "bindings": tuple(
                        {
                            "deployment_id": item.deployment_id,
                            "deployment_generation": item.deployment_generation,
                            "base_url": item.base_url,
                            "max_admitted_concurrency": item.max_admitted_concurrency,
                            "runtime_qualification_digest": item.runtime_qualification_digest,
                            "runtime_canary_evidence_digests": item.runtime_canary_evidence_digests,
                        }
                        for item in ordered
                    ),
                }
            ),
        )

    @property
    def role(self) -> str:
        return self.bindings[0].role

    @property
    def prompt_generation(self) -> str:
        return self.bindings[0].prompt_generation


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


@dataclass(frozen=True, slots=True)
class ModelEndpointPoolSnapshot:
    replica_set_digest: str
    selection_sequence: int
    replicas: tuple[ModelEndpointReplicaSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ModelEndpointDispatchResult:
    request: ModelEndpointRequest
    response: ModelEndpointResponse
    replica_set_digest: str
    selection_sequence: int
    dispatch_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.response.deployment_id != self.request.deployment_id:
            raise ValueError("model endpoint dispatch response deployment drift")
        object.__setattr__(
            self,
            "dispatch_digest",
            canonical_digest(
                {
                    "request_digest": self.request.digest(),
                    "response_digest": self.response.response_digest,
                    "replica_set_digest": self.replica_set_digest,
                    "selection_sequence": self.selection_sequence,
                }
            ),
        )


class QualifiedModelEndpointReplicaBindingPort(Protocol):
    def replica_set_for(
        self, *, role: str, prompt_generation: str
    ) -> QualifiedModelEndpointReplicaSet: ...


class ModelEndpointDispatchPoolPort(Protocol):
    """Minimal dispatch contract shared by operational and qualified pools."""

    def complete(
        self,
        request: ModelRequestEnvelope,
        body: Mapping[str, JsonInput],
    ) -> ModelEndpointDispatchResult: ...

    def snapshot(self) -> ModelEndpointPoolSnapshot: ...


class AdaptiveModelEndpointPoolPort(Protocol):
    @property
    def replica_set(self) -> QualifiedModelEndpointReplicaSet: ...

    def complete(
        self,
        request: ModelRequestEnvelope,
        body: Mapping[str, JsonInput],
    ) -> ModelEndpointDispatchResult: ...

    def snapshot(self) -> ModelEndpointPoolSnapshot: ...


__all__ = [
    "AdaptiveModelEndpointPoolPort",
    "ModelEndpointDispatchPoolPort",
    "ModelEndpointDispatchResult",
    "ModelEndpointPoolSnapshot",
    "ModelEndpointReplicaSnapshot",
    "OperationalModelEndpointReplica",
    "OperationalModelEndpointReplicaSet",
    "QualifiedModelEndpointReplicaBindingPort",
    "QualifiedModelEndpointReplicaSet",
]
