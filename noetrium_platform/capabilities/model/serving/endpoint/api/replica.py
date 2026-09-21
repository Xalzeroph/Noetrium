from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.foundation.kernel.kernel import canonical_digest, JsonInput

from .contracts import ModelEndpointRequest, ModelEndpointResponse
from .qualification import QualifiedModelEndpointBinding


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
    "ModelEndpointDispatchResult",
    "ModelEndpointPoolSnapshot",
    "ModelEndpointReplicaSnapshot",
    "QualifiedModelEndpointReplicaBindingPort",
    "QualifiedModelEndpointReplicaSet",
]
