from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from .contracts import SchedulingCandidate


class AdmissionSchedulingPolicyPort(Protocol):
    """Own the total admission ordering without owning capacity state."""

    def ordering_key(
        self,
        candidate: SchedulingCandidate,
        *,
        group_last_grant: Mapping[str, int],
        tenant_last_grant: Mapping[str, int],
        now_monotonic: float,
    ) -> tuple[int, ...]: ...

    def next_order_change_at(
        self,
        candidate: SchedulingCandidate,
        *,
        now_monotonic: float,
    ) -> float | None: ...

    def select(
        self,
        candidates: Iterable[SchedulingCandidate],
        *,
        group_last_grant: Mapping[str, int],
        tenant_last_grant: Mapping[str, int],
        now_monotonic: float,
    ) -> int: ...
