from __future__ import annotations

from collections.abc import Sequence
import math

from noetrium_platform.research.execution.scheduling.api import AdmissionSchedulingPolicyPort, ExecutionPriority, SchedulingCandidate


class FairPrioritySchedulingPolicy(AdmissionSchedulingPolicyPort):
    """Priority aging plus deterministic group fairness; owns ordering only."""

    def __init__(self, *, priority_aging_seconds: float = 1.0) -> None:
        if isinstance(priority_aging_seconds, bool) or not isinstance(priority_aging_seconds, (int, float)):
            raise TypeError("priority aging must be numeric")
        aging = float(priority_aging_seconds)
        if not math.isfinite(aging) or aging <= 0:
            raise ValueError("priority aging must be finite and positive")
        self._aging_seconds = aging
        self._rank = {ExecutionPriority.CRITICAL: 0, ExecutionPriority.HIGH: 1,
                      ExecutionPriority.NORMAL: 2, ExecutionPriority.LOW: 3}

    def _effective_rank(self, candidate: SchedulingCandidate, now: float) -> int:
        waited = max(0.0, now - candidate.enqueued_monotonic)
        return max(0, self._rank[candidate.priority] - int(waited / self._aging_seconds))

    def select(self, candidates: Sequence[SchedulingCandidate], *, group_last_grant: dict[str, int],
               now_monotonic: float) -> int:
        if not candidates:
            raise ValueError("scheduling candidates required")
        if any(not isinstance(candidate, SchedulingCandidate) for candidate in candidates):
            raise TypeError("scheduling candidates must be SchedulingCandidate values")
        if isinstance(now_monotonic, bool) or not isinstance(now_monotonic, (int, float)):
            raise TypeError("scheduling now_monotonic must be numeric")
        now_monotonic = float(now_monotonic)
        if not math.isfinite(now_monotonic) or now_monotonic < 0:
            raise ValueError("scheduling now_monotonic must be finite and non-negative")
        ranked = [(self._effective_rank(item, now_monotonic), item) for item in candidates]
        best_rank = min(rank for rank, _ in ranked)
        selected = min((item for rank, item in ranked if rank == best_rank),
                       key=lambda item: (group_last_grant.get(item.group_id, -1), item.ticket))
        return selected.ticket
