"""Batch projection for logically selected nested executable Units.

This module does not own child state, worker scheduling, thread/process pools, or
another lifecycle ledger.  It binds one immutable logical selection to a set of
ordinary UnitActivationRequest values, delegates physical dispatch to a
mechanics provider, and validates the returned authoritative child Machine cuts.

The provider may use threads, processes, remote workers, containers, or another
qualified mechanism.  Each child remains independently journal-authoritative;
the batch result is only a deterministic projection over those child links.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)

from noetrium_platform.foundation.kernel.kernel.unit_activation import (
    UnitActivationExecution,
    UnitActivationRuntime,
    UnitActivationRequest,
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
class UnitActivationBatchItem:
    """One selected logical participant bound to one exact child request."""

    participant_id: str
    request: UnitActivationRequest
    item_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.participant_id, "Unit activation batch participant_id")
        if not isinstance(self.request, UnitActivationRequest):
            raise TypeError(
                "Unit activation batch item requires UnitActivationRequest"
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
class UnitActivationBatchRequest:
    """Immutable ready-set/selection identity for nested Machine execution."""

    batch_id: str
    parent_machine_id: str
    selection_digest: str
    items: tuple[UnitActivationBatchItem, ...]
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.batch_id, "Unit activation batch batch_id")
        _text(self.parent_machine_id, "Unit activation batch parent_machine_id")
        _sha(self.selection_digest, "Unit activation batch selection_digest")
        if type(self.items) is not tuple or not self.items:
            raise ValueError("Unit activation batch items must be a non-empty tuple")
        if any(
            not isinstance(row, UnitActivationBatchItem)
            for row in self.items
        ):
            raise TypeError(
                "Unit activation batch items must contain UnitActivationBatchItem"
            )
        participant_ids = tuple(row.participant_id for row in self.items)
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("Unit activation batch participant ids must be unique")
        child_ids = tuple(row.request.child_machine_id for row in self.items)
        if len(child_ids) != len(set(child_ids)):
            raise ValueError("Unit activation batch unit activation ids must be unique")
        if any(
            row.request.parent_machine_id != self.parent_machine_id
            for row in self.items
        ):
            raise ValueError(
                "all Unit activation batch requests must share parent_machine_id"
            )
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest({
                "schema": "noetrium.unit-activation-batch-request.v3",
                "batch_id": self.batch_id,
                "parent_machine_id": self.parent_machine_id,
                "selection_digest": self.selection_digest,
                "items": tuple(
                    (row.participant_id, row.item_digest) for row in self.items
                ),
            }),
        )


@dataclass(frozen=True, slots=True)
class UnitActivationBatchMechanicsResult:
    """Provider mechanics output before platform validation/projection."""

    request_digest: str
    executions: tuple[UnitActivationExecution, ...]
    evidence_digests: tuple[str, ...] = ()
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        _sha(self.request_digest, "Unit activation batch mechanics request_digest")
        if type(self.executions) is not tuple or not self.executions:
            raise ValueError("Unit activation batch mechanics executions must be a non-empty tuple")
        if any(
            not isinstance(row, UnitActivationExecution)
            for row in self.executions
        ):
            raise TypeError(
                "Unit activation batch mechanics executions must contain typed child executions"
            )
        if type(self.evidence_digests) is not tuple:
            raise TypeError(
                "Unit activation batch mechanics evidence_digests must be a tuple"
            )
        evidence = tuple(
            sorted(
                _sha(row, "Unit activation batch mechanics evidence digest")
                for row in self.evidence_digests
            )
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError(
                "Unit activation batch mechanics evidence digests must be unique"
            )
        object.__setattr__(self, "evidence_digests", evidence)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


@runtime_checkable
class UnitActivationBatchPort(Protocol):
    """Optional batch capability orthogonal to the single-child Method ABI."""

    @property
    def identity_digest(self) -> str: ...

    def execute_batch(
        self,
        request: UnitActivationBatchRequest,
    ) -> "UnitActivationBatchExecution": ...


@runtime_checkable
class UnitActivationBatchMechanicsPort(Protocol):
    """Physical dispatch seam; owns no research state or child truth."""

    @property
    def identity_digest(self) -> str: ...

    @property
    def activation_runtime_identity_digest(self) -> str: ...

    def execute_batch(
        self,
        request: UnitActivationBatchRequest,
    ) -> UnitActivationBatchMechanicsResult: ...


@dataclass(frozen=True, slots=True)
class UnitActivationBatchExecution:
    """Deterministic projection over independently authoritative child cuts."""

    request_digest: str
    executions: tuple[UnitActivationExecution, ...]
    evidence_digests: tuple[str, ...]
    mechanics_identity_digest: str
    receipt: JsonValue = None
    receipt_digest: str = field(init=False)
    execution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "Unit activation batch execution request_digest")
        if type(self.executions) is not tuple or not self.executions:
            raise ValueError(
                "Unit activation batch execution requires non-empty executions"
            )
        if any(
            not isinstance(row, UnitActivationExecution)
            for row in self.executions
        ):
            raise TypeError(
                "Unit activation batch execution rows must be typed child executions"
            )
        evidence = tuple(
            sorted(
                _sha(row, "Unit activation batch execution evidence digest")
                for row in self.evidence_digests
            )
        )
        if len(evidence) != len(set(evidence)):
            raise ValueError(
                "Unit activation batch execution evidence digests must be unique"
            )
        object.__setattr__(self, "evidence_digests", evidence)
        mechanics = _sha(
            self.mechanics_identity_digest,
            "Unit activation batch mechanics identity_digest",
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
                "schema": "noetrium.unit-activation-batch-execution.v3",
                "request_digest": self.request_digest,
                "children": tuple(
                    {
                        "machine_id": row.execution.machine_id,
                        "revision": row.execution.revision,
                        "status": row.execution.status.value,
                        "cut_digest": row.execution.cut.cut_digest,
                        "unit_digest": row.link.child_unit_digest,
                        "execution_lock_digest": (
                            row.link.child_execution_lock_digest
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


def execute_unit_activation_batch(
    activation_runtime: UnitActivationRuntime,
    mechanics: UnitActivationBatchMechanicsPort,
    request: UnitActivationBatchRequest,
) -> UnitActivationBatchExecution:
    """Execute one batch through the canonical UnitActivationRuntime."""

    if not isinstance(activation_runtime, UnitActivationRuntime):
        raise TypeError("Unit activation batch requires UnitActivationRuntime")
    if not isinstance(mechanics, UnitActivationBatchMechanicsPort):
        raise TypeError(
            "Unit activation batch requires UnitActivationBatchMechanicsPort"
        )
    if not isinstance(request, UnitActivationBatchRequest):
        raise TypeError(
            "Unit activation batch requires UnitActivationBatchRequest"
        )
    require_sha256(
        mechanics.identity_digest,
        "Unit activation batch mechanics identity_digest",
    )
    if (
        mechanics.activation_runtime_identity_digest
        != activation_runtime.identity_digest
    ):
        raise ValueError(
            "Unit activation batch mechanics is bound to another Unit activation runtime"
        )

    result = mechanics.execute_batch(request)
    if not isinstance(result, UnitActivationBatchMechanicsResult):
        raise TypeError(
            "Unit activation batch mechanics must return "
            "UnitActivationBatchMechanicsResult"
        )
    if result.request_digest != request.request_digest:
        raise ValueError("Unit activation batch mechanics request identity mismatch")
    if len(result.executions) != len(request.items):
        raise ValueError(
            "Unit activation batch execution cardinality drifted from request"
        )

    for item, execution in zip(
        request.items,
        result.executions,
        strict=True,
    ):
        expected = item.request
        if execution.execution.machine_id != expected.child_machine_id:
            raise ValueError(
                "Unit activation batch execution order/child identity mismatch"
            )
        link = execution.link
        if link.parent_machine_id != request.parent_machine_id:
            raise ValueError("Unit activation batch link parent identity mismatch")
        if link.child_machine_id != expected.child_machine_id:
            raise ValueError("Unit activation batch link child identity mismatch")

    return UnitActivationBatchExecution(
        request_digest=request.request_digest,
        executions=result.executions,
        evidence_digests=result.evidence_digests,
        mechanics_identity_digest=mechanics.identity_digest,
        receipt=result.receipt,
    )


__all__ = [

    "UnitActivationBatchExecution",
    "UnitActivationBatchItem",
    "UnitActivationBatchPort",
    "UnitActivationBatchMechanicsPort",
    "UnitActivationBatchMechanicsResult",
    "UnitActivationBatchRequest",
    "execute_unit_activation_batch",
]
