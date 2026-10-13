from __future__ import annotations
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort

from typing import Protocol, runtime_checkable

from .contracts import (
    StudyExecutionUnit,
    StudyMetricObservation,
)
from .plan import VariantBinding


@runtime_checkable
class BoundStudyExecutionPort(Protocol):
    """Complete provider seam for execution of one frozen study execution graph.

    The provider receives only assignments plus their frozen VariantBindings.
    Both grouped and independent-variant entrypoints are mandatory so scientific
    concurrency policy never changes the provider contract at runtime.
    """

    def execute_bound(
        self,
        unit: StudyExecutionUnit,
        bindings: tuple[VariantBinding, ...],
        plan_digest: str,
        *,
        execution_context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> tuple[StudyMetricObservation, ...]: ...

    def execute_bound_variant(
        self,
        assignment: NoetriumUnit,
        binding: VariantBinding,
        plan_digest: str,
        *,
        execution_context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> StudyMetricObservation: ...


__all__ = [
    "BoundStudyExecutionPort",
]
