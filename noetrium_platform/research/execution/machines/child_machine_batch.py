"""Batch projection for logically selected nested Research Machines.

This module does not own child state, worker scheduling, thread/process pools, or
another lifecycle ledger.  It binds one immutable logical selection to a set of
ordinary ChildResearchMachineRequest values, delegates physical dispatch to a
mechanics provider, and validates the returned authoritative child Machine cuts.

The provider may use threads, processes, remote workers, containers, or another
qualified mechanism.  Each child remains independently journal-authoritative;
the batch result is only a deterministic projection over those child links.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)

from .child_machine import (
    ChildResearchMachineExecution,
    ChildResearchMachineExecutor,
    ChildResearchMachineRequest,
)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _sha(value: object, field_name: str) -> str:
    return require_sha256(
        _text(value, field_name),
        field_name,
    )



@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchItem:
    """One selected logical participant bound to one exact child request."""

    participant_id: str
    request: ChildResearchMachineRequest
    item_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.participant_id, "child batch participant_id")
        if not isinstance(self.request, ChildResearchMachineRequest):
            raise TypeError(
                "child batch item requires ChildResearchMachineRequest"
            )
        object.__setattr__(
            self,
            "item_digest",
            canonical_digest({
                "participant_id": self.participant_id,
                "request_digest": self.request.request_digest,
            }),
        )


@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchRequest:
    """Immutable ready-set/selection identity for nested Machine execution."""

    batch_id: str
    parent_machine_id: str
    selection_digest: str
    items: tuple[ChildResearchMachineBatchItem, ...]
    dispatch_parallelism: int = 1
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.batch_id, "child batch batch_id")
        _text(self.parent_machine_id, "child batch parent_machine_id")
        _sha(self.selection_digest, "child batch selection_digest")
        if type(self.items) is not tuple or not self.items:
            raise ValueError("child batch items must be a non-empty tuple")
        if any(
            not isinstance(row, ChildResearchMachineBatchItem)
            for row in self.items
        ):
            raise TypeError(
                "child batch items must contain ChildResearchMachineBatchItem"
            )
        participant_ids = tuple(row.participant_id for row in self.items)
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("child batch participant ids must be unique")
        child_ids = tuple(row.request.child_machine_id for row in self.items)
        if len(child_ids) != len(set(child_ids)):
            raise ValueError("child batch child machine ids must be unique")
        if any(
            row.request.parent_machine_id != self.parent_machine_id
            for row in self.items
        ):
            raise ValueError(
                "all child batch requests must share parent_machine_id"
            )
        if type(self.dispatch_parallelism) is not int or self.dispatch_parallelism < 1:
            raise ValueError("child batch dispatch_parallelism must be positive")
        if self.dispatch_parallelism > len(self.items):
            raise ValueError(
                "child batch dispatch_parallelism cannot exceed item count"
            )
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest({
                "schema": "noetrium.child-research-machine-batch-request.v2",
                "batch_id": self.batch_id,
                "parent_machine_id": self.parent_machine_id,
                "selection_digest": self.selection_digest,
                "dispatch_parallelism": self.dispatch_parallelism,
                "items": tuple(
                    (row.participant_id, row.item_digest) for row in self.items
                ),
            }),
        )


@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchMechanicsResult:
    """Provider mechanics output before platform validation/projection."""

    request_digest: str
    dispatch_parallelism: int
    executions: tuple[ChildResearchMachineExecution, ...]
    evidence_digests: tuple[str, ...] = ()
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        _sha(self.request_digest, "child batch mechanics request_digest")
        if type(self.dispatch_parallelism) is not int or self.dispatch_parallelism < 1:
            raise ValueError(
                "child batch mechanics dispatch_parallelism must be positive"
            )
        if type(self.executions) is not tuple or not self.executions:
            raise ValueError("child batch mechanics executions must be a non-empty tuple")
        if self.dispatch_parallelism > len(self.executions):
            raise ValueError(
                "child batch mechanics dispatch_parallelism exceeds execution count"
            )
        if any(
            not isinstance(row, ChildResearchMachineExecution)
            for row in self.executions
        ):
            raise TypeError(
                "child batch mechanics executions must contain typed child executions"
            )
        if type(self.evidence_digests) is not tuple:
            raise TypeError(
                "child batch mechanics evidence_digests must be a tuple"
            )
        evidence = tuple(
            sorted(
                _sha(row, "child batch mechanics evidence digest")
                for row in self.evidence_digests
            )
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError(
                "child batch mechanics evidence digests must be unique"
            )
        if self.dispatch_parallelism > 1 and not evidence:
            raise ValueError(
                "parallel child batch mechanics requires dispatch evidence"
            )
        object.__setattr__(self, "evidence_digests", evidence)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


@runtime_checkable
class ChildResearchMachineBatchPort(Protocol):
    """Optional batch capability orthogonal to the single-child Method ABI."""

    @property
    def identity_digest(self) -> str: ...

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> "ChildResearchMachineBatchExecution": ...


@runtime_checkable
class ChildResearchMachineBatchMechanicsPort(Protocol):
    """Physical dispatch seam; owns no research state or child truth."""

    @property
    def identity_digest(self) -> str: ...

    @property
    def child_executor_identity_digest(self) -> str: ...

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchMechanicsResult: ...


@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchExecution:
    """Deterministic projection over independently authoritative child cuts."""

    request_digest: str
    dispatch_parallelism: int
    executions: tuple[ChildResearchMachineExecution, ...]
    evidence_digests: tuple[str, ...]
    mechanics_identity_digest: str
    receipt: JsonValue = None
    receipt_digest: str = field(init=False)
    execution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "child batch execution request_digest")
        if type(self.dispatch_parallelism) is not int or self.dispatch_parallelism < 1:
            raise ValueError("child batch execution dispatch_parallelism must be positive")
        if type(self.executions) is not tuple or not self.executions:
            raise ValueError(
                "child batch execution requires non-empty executions"
            )
        if self.dispatch_parallelism > len(self.executions):
            raise ValueError("child batch execution dispatch_parallelism exceeds execution count")
        if any(
            not isinstance(row, ChildResearchMachineExecution)
            for row in self.executions
        ):
            raise TypeError(
                "child batch execution rows must be typed child executions"
            )
        evidence = tuple(
            sorted(
                _sha(row, "child batch execution evidence digest")
                for row in self.evidence_digests
            )
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError(
                "child batch execution evidence digests must be unique"
            )
        object.__setattr__(self, "evidence_digests", evidence)
        if self.dispatch_parallelism > 1 and not evidence:
            raise ValueError("parallel child batch execution requires dispatch evidence")
        mechanics = _sha(
            self.mechanics_identity_digest,
            "child batch mechanics identity_digest",
        )
        object.__setattr__(self, "mechanics_identity_digest", mechanics)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(self.receipt),
        )
        object.__setattr__(
            self,
            "execution_digest",
            canonical_digest({
                "schema": "noetrium.child-research-machine-batch-execution.v2",
                "request_digest": self.request_digest,
                "dispatch_parallelism": self.dispatch_parallelism,
                "children": tuple(
                    {
                        "machine_id": row.execution.machine_id,
                        "revision": row.execution.revision,
                        "status": row.execution.status.value,
                        "cut_digest": row.execution.cut.cut_digest,
                        "program_digest": row.link.child_program_digest,
                        "program_lock_digest": (
                            row.link.child_program_lock_digest
                        ),
                        "snapshot_ref": row.link.child_snapshot_ref,
                        "result_ref": row.link.child_result_ref,
                    }
                    for row in self.executions
                ),
                "evidence_digests": evidence,
                "mechanics_identity_digest": mechanics,
                "receipt_digest": self.receipt_digest,
            }),
        )

    @property
    def links(self):
        return tuple(row.link for row in self.executions)

    @property
    def results(self):
        return tuple(row.result for row in self.executions)


def execute_child_research_machine_batch(
    executor: ChildResearchMachineExecutor,
    mechanics: ChildResearchMachineBatchMechanicsPort,
    request: ChildResearchMachineBatchRequest,
) -> ChildResearchMachineBatchExecution:
    """Execute one batch through the single child-machine executor."""

    if not isinstance(executor, ChildResearchMachineExecutor):
        raise TypeError("child batch requires ChildResearchMachineExecutor")
    if not isinstance(mechanics, ChildResearchMachineBatchMechanicsPort):
        raise TypeError(
            "child batch requires ChildResearchMachineBatchMechanicsPort"
        )
    if not isinstance(request, ChildResearchMachineBatchRequest):
        raise TypeError(
            "child batch requires ChildResearchMachineBatchRequest"
        )
    require_sha256(
        mechanics.identity_digest,
        "child batch mechanics identity_digest",
    )
    if (
        mechanics.child_executor_identity_digest
        != executor.identity_digest
    ):
        raise ValueError(
            "child batch mechanics is bound to another child executor"
        )

    result = mechanics.execute_batch(request)
    if not isinstance(result, ChildResearchMachineBatchMechanicsResult):
        raise TypeError(
            "child batch mechanics must return "
            "ChildResearchMachineBatchMechanicsResult"
        )
    if result.request_digest != request.request_digest:
        raise ValueError("child batch mechanics request identity mismatch")
    if result.dispatch_parallelism != request.dispatch_parallelism:
        raise ValueError(
            "child batch mechanics dispatch_parallelism drifted from request"
        )
    if len(result.executions) != len(request.items):
        raise ValueError(
            "child batch execution cardinality drifted from request"
        )

    for item, execution in zip(
        request.items,
        result.executions,
        strict=True,
    ):
        expected = item.request
        if execution.execution.machine_id != expected.child_machine_id:
            raise ValueError(
                "child batch execution order/child identity mismatch"
            )
        link = execution.link
        if link.parent_machine_id != request.parent_machine_id:
            raise ValueError("child batch link parent identity mismatch")
        if link.child_machine_id != expected.child_machine_id:
            raise ValueError("child batch link child identity mismatch")

    return ChildResearchMachineBatchExecution(
        request_digest=request.request_digest,
        dispatch_parallelism=result.dispatch_parallelism,
        executions=result.executions,
        evidence_digests=result.evidence_digests,
        mechanics_identity_digest=mechanics.identity_digest,
        receipt=result.receipt,
    )


__all__ = [

    "ChildResearchMachineBatchExecution",
    "ChildResearchMachineBatchItem",
    "ChildResearchMachineBatchPort",
    "ChildResearchMachineBatchMechanicsPort",
    "ChildResearchMachineBatchMechanicsResult",
    "ChildResearchMachineBatchRequest",
    "execute_child_research_machine_batch",
]
