from __future__ import annotations

from collections.abc import Iterable, Mapping
import math

from noetrium_platform.research.execution.policy.scheduling.api import (
    AdmissionSchedulingPolicyPort,
    ExecutionPriority,
    SchedulingCandidate,
)


class FairPrioritySchedulingPolicy(AdmissionSchedulingPolicyPort):
    """Priority aging plus work-conserving tenant/group fairness; owns ordering only."""

    def __init__(self, *, priority_aging_seconds: float = 1.0) -> None:
        if isinstance(priority_aging_seconds, bool) or not isinstance(
            priority_aging_seconds, (int, float)
        ):
            raise TypeError("priority aging must be numeric")
        aging = float(priority_aging_seconds)
        if not math.isfinite(aging) or aging <= 0:
            raise ValueError("priority aging must be finite and positive")
        self._aging_seconds = aging
        self._rank = {
            ExecutionPriority.CRITICAL: 0,
            ExecutionPriority.HIGH: 1,
            ExecutionPriority.NORMAL: 2,
            ExecutionPriority.LOW: 3,
        }

    def _effective_rank(self, candidate: SchedulingCandidate, now: float) -> int:
        waited = max(0.0, now - candidate.enqueued_monotonic)
        return max(
            0,
            self._rank[candidate.priority] - int(waited / self._aging_seconds),
        )

    @staticmethod
    def _validated_now(now_monotonic: float) -> float:
        if isinstance(now_monotonic, bool) or not isinstance(
            now_monotonic, (int, float)
        ):
            raise TypeError("scheduling now_monotonic must be numeric")
        now = float(now_monotonic)
        if not math.isfinite(now) or now < 0:
            raise ValueError(
                "scheduling now_monotonic must be finite and non-negative"
            )
        return now

    def ordering_key(
        self,
        candidate: SchedulingCandidate,
        *,
        group_last_grant: Mapping[str, int],
        tenant_last_grant: Mapping[str, int],
        now_monotonic: float,
    ) -> tuple[int, ...]:
        if not isinstance(candidate, SchedulingCandidate):
            raise TypeError(
                "scheduling candidates must be SchedulingCandidate values"
            )
        now = self._validated_now(now_monotonic)
        owner_last_grant = (
            tenant_last_grant.get(candidate.tenant_id, -1)
            if candidate.tenant_id is not None
            else group_last_grant.get(candidate.group_id, -1)
        )
        return (
            self._effective_rank(candidate, now),
            candidate.tenant_in_flight,
            owner_last_grant,
            candidate.group_in_flight,
            group_last_grant.get(candidate.group_id, -1),
            candidate.ticket,
        )

    def next_order_change_at(
        self,
        candidate: SchedulingCandidate,
        *,
        now_monotonic: float,
    ) -> float | None:
        if not isinstance(candidate, SchedulingCandidate):
            raise TypeError(
                "scheduling candidate must be SchedulingCandidate"
            )
        now = self._validated_now(now_monotonic)
        base_rank = self._rank[candidate.priority]
        waited = max(0.0, now - candidate.enqueued_monotonic)
        elapsed_steps = int(waited / self._aging_seconds)
        if base_rank - elapsed_steps <= 0:
            return None
        return (
            candidate.enqueued_monotonic
            + (elapsed_steps + 1) * self._aging_seconds
        )

    def select(
        self,
        candidates: Iterable[SchedulingCandidate],
        *,
        group_last_grant: Mapping[str, int],
        tenant_last_grant: Mapping[str, int],
        now_monotonic: float,
    ) -> int:
        now = self._validated_now(now_monotonic)
        selected = min(
            candidates,
            key=lambda candidate: self.ordering_key(
                candidate,
                group_last_grant=group_last_grant,
                tenant_last_grant=tenant_last_grant,
                now_monotonic=now,
            ),
            default=None,
        )
        if selected is None:
            raise ValueError("scheduling candidates required")
        return selected.ticket
