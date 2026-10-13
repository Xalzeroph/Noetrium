from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from noetrium_platform.capabilities.model.serving.endpoint.api.replica import (
    ModelEndpointReplicaSelectionCandidate,
)
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
    current_runtime_cost_scope,
)


MODEL_REPLICA_ROUTING_COMPLEXITY = ComplexityContract(
    algorithm_id="model.replica-routing.deficit-locality.v4",
    implementation_digest=canonical_digest(
        (
            "model.replica-routing.deficit-locality.v4",
            "single-pass-d2lpm-pressure-order",
        )
    ),
    time_upper_bound=ComplexityBound.linear("model_replica_candidates"),
    space_upper_bound=ComplexityBound.constant(),
    assumptions=(
        "exact routing must distinguish any interchangeable replica whose live pressure can change the optimum",
        "candidate records are streamed without materializing a replica-sized buffer",
        "per-owner worker deficit and longest-prefix membership are O(1) candidate attributes",
        "worker-deficit exhaustion causes at most one additional replica scan after an algebraically batched refill",
    ),
    time_lower_bound=ComplexityBound.linear("model_replica_candidates"),
    space_lower_bound=ComplexityBound.constant(),
)


@dataclass(frozen=True, slots=True)
class DeficitPrefixPressureReplicaSelectionPolicy:
    """D2LPM-style worker choice with live-pressure tie-breaking.

    Retry/capacity are hard physical partitions. Within those constraints,
    positive per-owner worker deficit bounds locality stickiness, global
    longest-prefix membership preserves cache reuse, and live pressure
    deterministically chooses the worker inside the resulting class.
    """

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "policy": "deficit-prefix-pressure-model-replica.v2",
                "signals": (
                    "retry_diversity",
                    "adaptive_window_saturation",
                    "owner_worker_deficit",
                    "global_longest_prefix_match",
                    "runtime_queue_observation",
                    "normalized_in_flight",
                    "runtime_kv_pressure",
                    "consecutive_failures",
                    "observed_latency",
                    "selection_recency",
                ),
            }
        )

    @staticmethod
    def _normalized_load(
        candidate: ModelEndpointReplicaSelectionCandidate,
    ) -> float:
        return candidate.in_flight / candidate.capacity

    @staticmethod
    def _latency_rank(
        candidate: ModelEndpointReplicaSelectionCandidate,
    ) -> float:
        return (
            -1.0
            if candidate.ewma_latency_seconds is None
            else candidate.ewma_latency_seconds
        )

    @staticmethod
    def _queue_confidence_rank(
        candidate: ModelEndpointReplicaSelectionCandidate,
    ) -> tuple[int, int]:
        if not candidate.runtime_pressure_observed:
            return (1, 0)
        if candidate.runtime_requests_waiting == 0:
            return (0, 0)
        return (2, candidate.runtime_requests_waiting)

    @classmethod
    def _pressure_key(
        cls,
        candidate: ModelEndpointReplicaSelectionCandidate,
    ) -> tuple[object, ...]:
        return (
            cls._normalized_load(candidate),
            candidate.runtime_gpu_kv_cache_usage,
            candidate.consecutive_failures,
            cls._latency_rank(candidate),
            candidate.last_selected_sequence,
            candidate.deployment_id,
        )

    def select(
        self,
        candidates: Iterable[ModelEndpointReplicaSelectionCandidate],
    ) -> str:
        cost_scope = current_runtime_cost_scope()
        candidate_count = 0
        best_key: tuple[object, ...] | None = None
        best_id: str | None = None

        for row in candidates:
            if not isinstance(row, ModelEndpointReplicaSelectionCandidate):
                raise TypeError(
                    "deficit replica selection requires typed candidates"
                )
            candidate_count += 1
            queue_rank = self._queue_confidence_rank(row)
            key = (
                1 if row.attempted_in_dispatch else 0,
                1 if row.in_flight >= row.capacity else 0,
                0 if row.worker_deficit_positive else 1,
                0 if row.global_longest_prefix_match else 1,
                queue_rank[0],
                queue_rank[1],
                *self._pressure_key(row),
                -row.prefix_affinity_depth,
                row.deployment_id,
            )
            if best_key is None or key < best_key:
                best_key = key
                best_id = row.deployment_id

        if cost_scope is not None:
            cost_scope.set_scale(
                "model_replica_candidates",
                candidate_count,
            )
            cost_scope.add_work(
                "model_replica_candidates_examined",
                candidate_count,
            )
        if best_id is None:
            raise ValueError("deficit replica selection requires candidates")
        return best_id



@dataclass(frozen=True, slots=True)
class PinnedReplicaSelectionPolicy:
    """Explicit downstream placement constraint with no implicit fallback."""

    deployment_id: str

    def __post_init__(self) -> None:
        if type(self.deployment_id) is not str or not self.deployment_id.strip():
            raise ValueError("pinned replica selection deployment_id is required")

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "policy": "pinned-model-replica.v1",
                "deployment_id": self.deployment_id,
            }
        )

    def select(
        self,
        candidates: Iterable[ModelEndpointReplicaSelectionCandidate],
    ) -> str:
        for row in candidates:
            if not isinstance(row, ModelEndpointReplicaSelectionCandidate):
                raise TypeError("pinned replica selection requires typed candidates")
            if row.deployment_id == self.deployment_id:
                return self.deployment_id
        raise ValueError(
            "pinned model replica is not currently eligible: "
            + self.deployment_id
        )


__all__ = [
    "DeficitPrefixPressureReplicaSelectionPolicy",
    "MODEL_REPLICA_ROUTING_COMPLEXITY",
    "PinnedReplicaSelectionPolicy",
]
