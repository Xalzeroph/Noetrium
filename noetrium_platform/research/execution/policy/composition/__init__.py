from __future__ import annotations

from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.policy.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import SchedulingAuthorityPort


def build_execution_admission(
    *,
    budget: AdmissionBudget,
    scheduling_authority: SchedulingAuthorityPort,
) -> HierarchicalAdmissionAuthority:
    return HierarchicalAdmissionAuthority(
        budget=budget,
        scheduling_authority=scheduling_authority,
    )


__all__ = ["build_execution_admission"]
