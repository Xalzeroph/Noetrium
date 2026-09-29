from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.model.serving.endpoint.api.replica import (
    ModelEndpointReplicaSelectionCandidate,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


@dataclass(frozen=True, slots=True)
class AdaptiveLeastPressureReplicaSelectionPolicy:
    """Resource-adaptive default for interchangeable model replicas.

    Selection is based only on live pool facts. The policy is infrastructure-
    independent: it contains no deployment names, ports, hosts, GPUs or model ids.
    """

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "policy": "adaptive-least-pressure-model-replica.v2",
            "signals": (
                "retry_diversity",
                "saturation",
                "normalized_in_flight",
                "consecutive_failures",
                "prefix_affinity",
                "observed_latency",
                "selection_recency",
            ),
        })

    def select(
        self,
        candidates: tuple[ModelEndpointReplicaSelectionCandidate, ...],
    ) -> str:
        if type(candidates) is not tuple or not candidates:
            raise ValueError("adaptive replica selection requires candidates")

        def score(candidate: ModelEndpointReplicaSelectionCandidate):
            saturated = 1 if candidate.in_flight >= candidate.capacity else 0
            normalized_load = candidate.in_flight / candidate.capacity
            latency_rank = (
                -1.0
                if candidate.ewma_latency_seconds is None
                else candidate.ewma_latency_seconds
            )
            # Retry diversity is first: when scientifically interchangeable
            # replicas exist, do not spend a retry on the same physical target
            # unless every currently admissible candidate was already tried.
            #
            # Prefix affinity is deliberately considered only after pressure
            # and health. This gives sequential/shared-prefix agent traffic KV
            # locality while preserving load spreading under concurrency.
            return (
                1 if candidate.attempted_in_dispatch else 0,
                saturated,
                normalized_load,
                candidate.consecutive_failures,
                -candidate.prefix_affinity_score,
                -candidate.prefix_affinity_depth,
                latency_rank,
                candidate.last_selected_sequence,
                candidate.deployment_id,
            )

        return min(candidates, key=score).deployment_id


@dataclass(frozen=True, slots=True)
class PinnedReplicaSelectionPolicy:
    """Explicit downstream placement constraint with no implicit fallback."""

    deployment_id: str

    def __post_init__(self) -> None:
        if type(self.deployment_id) is not str or not self.deployment_id.strip():
            raise ValueError("pinned replica selection deployment_id is required")

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "policy": "pinned-model-replica.v1",
            "deployment_id": self.deployment_id,
        })

    def select(
        self,
        candidates: tuple[ModelEndpointReplicaSelectionCandidate, ...],
    ) -> str:
        return self.deployment_id


__all__ = [
    "AdaptiveLeastPressureReplicaSelectionPolicy",
    "PinnedReplicaSelectionPolicy",
]
