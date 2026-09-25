from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .contracts import SchedulingCandidate


class AdmissionSchedulingPolicyPort(Protocol):
    """Select one admissible ticket without owning resource/admission state."""

    def select(
        self,
        candidates: Sequence[SchedulingCandidate],
        *,
        group_last_grant: dict[str, int],
        now_monotonic: float,
    ) -> int: ...
