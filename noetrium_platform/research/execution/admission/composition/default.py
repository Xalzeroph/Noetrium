from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafHandler
from noetrium_platform.research.execution.admission.api import AdmissionBudget
from noetrium_platform.research.execution.admission.providers.default import bind as bind_provider
from noetrium_platform.research.execution.admission.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.research.execution.scheduling.api import AdmissionSchedulingPolicyPort


def compose(handler: LeafHandler, state_path=None):
    """Compose the standard executable leaf boundary for execution/admission."""
    return bind_provider(handler, state_path)


def build_execution_admission(
    *,
    budget: AdmissionBudget,
    scheduling: AdmissionSchedulingPolicyPort,
) -> HierarchicalAdmissionAuthority:
    """Compose the domain admission authority from explicit policy dependencies."""
    return HierarchicalAdmissionAuthority(budget=budget, scheduling=scheduling)


__all__ = ["compose", "build_execution_admission"]
