from __future__ import annotations

from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.policy.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.research.execution.policy.api import AdmissionSchedulingPolicyPort


def build_execution_admission(
    *,
    budget: AdmissionBudget,
    scheduling: AdmissionSchedulingPolicyPort,
) -> HierarchicalAdmissionAuthority:
    return HierarchicalAdmissionAuthority(budget=budget, scheduling=scheduling)


__all__ = ["build_execution_admission"]

from noetrium_platform.research.execution.policy.runtime import FairPrioritySchedulingPolicy

def build_admission_scheduling_policy(*, priority_aging_seconds: float = 1.0) -> FairPrioritySchedulingPolicy:
    return FairPrioritySchedulingPolicy(priority_aging_seconds=priority_aging_seconds)

__all__ = tuple(__all__) + ("build_admission_scheduling_policy",)
