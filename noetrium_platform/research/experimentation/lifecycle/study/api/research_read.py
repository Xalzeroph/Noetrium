"""Producer-owned typed read contracts for study research results.

The read port exposes an immutable projection of authoritative Study records.
It is a source seam, not a second store or a consumer-owned query registry.
"""
from __future__ import annotations


from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.api import NoetriumUnit, ScopeKind, scope_id, scope_kind

from .benchmark import require_benchmark
from .measurement import MeasurementRecord
from .trial import TrialExecutionReceipt


@dataclass(frozen=True, slots=True)
class StudyResearchReadSnapshot:
    scope: NoetriumUnit
    task_sets: tuple[NoetriumUnit, ...] = ()
    trial_receipts: tuple[TrialExecutionReceipt, ...] = ()
    measurements: tuple[MeasurementRecord, ...] = ()
    snapshot_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.scope) is not NoetriumUnit:
            raise TypeError("study research snapshot scope must be NoetriumUnit")
        if type(self.task_sets) is not tuple or any(
            type(row) is not NoetriumUnit for row in self.task_sets
        ):
            raise TypeError("study research snapshot task_sets must contain Units")
        for row in self.task_sets:
            require_benchmark(row)
        if type(self.trial_receipts) is not tuple or any(
            type(row) is not TrialExecutionReceipt for row in self.trial_receipts
        ):
            raise TypeError("study research snapshot trial_receipts must contain TrialExecutionReceipt")
        if type(self.measurements) is not tuple or any(
            type(row) is not MeasurementRecord for row in self.measurements
        ):
            raise TypeError("study research snapshot measurements must contain MeasurementRecord")
        if len({(row.unit_id, str(row.parameters["revision_id"])) for row in self.task_sets}) != len(self.task_sets):
            raise ValueError("study research snapshot task sets must have unique identities")
        if len({row.request_digest for row in self.trial_receipts}) != len(self.trial_receipts):
            raise ValueError("study research snapshot trial receipts must be unique")
        if len({row.record_digest for row in self.measurements}) != len(self.measurements):
            raise ValueError("study research snapshot measurements must be unique")
        effective_measurements = tuple(self.measurements) + tuple(
            row
            for receipt in self.trial_receipts
            for row in receipt.measurements
        )
        if scope_kind(self.scope) is ScopeKind.RUN and any(
            row.run_id != scope_id(self.scope) for row in effective_measurements
        ):
            raise ValueError("run-scoped study research snapshot contains a foreign measurement")
        if scope_kind(self.scope) is ScopeKind.STUDY and any(
            row.study_id != scope_id(self.scope) for row in effective_measurements
        ):
            raise ValueError("study-scoped research snapshot contains a foreign measurement")
        nested_measurements = {
            row.record_digest
            for receipt in self.trial_receipts
            for row in receipt.measurements
        }
        nested_measurements.update(row.record_digest for row in self.measurements)
        object.__setattr__(
            self,
            "snapshot_digest",
            canonical_digest(
                {
                    "scope": self.scope,
                    "task_sets": tuple(row.unit_digest for row in self.task_sets),
                    "trial_receipts": tuple(row.receipt_digest for row in self.trial_receipts),
                    "measurements": tuple(sorted(nested_measurements)),
                }
            ),
        )


class StudyResearchReadPort(Protocol):
    """Public producer-owned read authority for Study result projections."""

    def snapshot(self) -> StudyResearchReadSnapshot: ...


__all__ = ["StudyResearchReadPort", "StudyResearchReadSnapshot"]
