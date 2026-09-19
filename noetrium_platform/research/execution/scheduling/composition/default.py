from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafHandler
from noetrium_platform.research.execution.scheduling.providers.default import bind as bind_provider
from noetrium_platform.research.execution.scheduling.runtime import FairPrioritySchedulingPolicy


def compose(handler: LeafHandler, state_path=None):
    """Compose the standard executable leaf boundary for execution/scheduling."""
    return bind_provider(handler, state_path)


def build_admission_scheduling_policy(*, priority_aging_seconds: float = 1.0) -> FairPrioritySchedulingPolicy:
    """Compose the scheduling policy used by execution/admission."""
    return FairPrioritySchedulingPolicy(priority_aging_seconds=priority_aging_seconds)


__all__ = ["compose", "build_admission_scheduling_policy"]
