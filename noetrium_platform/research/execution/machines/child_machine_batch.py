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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Barrier, BrokenBarrierError
from time import monotonic_ns
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
    ChildResearchMachineRequest,
    RegisteredChildResearchMachineExecutor,
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


class ChildBatchExecutionMode(StrEnum):
    SERIAL = "serial"
    CONCURRENT = "concurrent"


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
                "request": thaw_json(self.request.as_payload()),
            }),
        )


@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchRequest:
    """Immutable ready-set/selection identity for nested Machine execution."""

    batch_id: str
    parent_machine_id: str
    selection_digest: str
    items: tuple[ChildResearchMachineBatchItem, ...]
    require_concurrent: bool = False
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
        if type(self.require_concurrent) is not bool:
            raise TypeError("child batch require_concurrent must be boolean")
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest({
                "schema": "noetrium.child-research-machine-batch-request.v1",
                "batch_id": self.batch_id,
                "parent_machine_id": self.parent_machine_id,
                "selection_digest": self.selection_digest,
                "require_concurrent": self.require_concurrent,
                "items": tuple(
                    (row.participant_id, row.item_digest) for row in self.items
                ),
            }),
        )


@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchMechanicsResult:
    """Provider mechanics output before platform validation/projection."""

    request_digest: str
    mode: ChildBatchExecutionMode
    executions: tuple[ChildResearchMachineExecution, ...]
    evidence_digests: tuple[str, ...] = ()
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        _sha(self.request_digest, "child batch mechanics request_digest")
        if not isinstance(self.mode, ChildBatchExecutionMode):
            raise TypeError(
                "child batch mechanics mode must be ChildBatchExecutionMode"
            )
        if type(self.executions) is not tuple:
            raise TypeError("child batch mechanics executions must be a tuple")
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

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchMechanicsResult: ...


@dataclass(frozen=True, slots=True)
class ChildResearchMachineBatchExecution:
    """Deterministic projection over independently authoritative child cuts."""

    request_digest: str
    mode: ChildBatchExecutionMode
    executions: tuple[ChildResearchMachineExecution, ...]
    evidence_digests: tuple[str, ...]
    mechanics_identity_digest: str
    receipt: JsonValue = None
    execution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "child batch execution request_digest")
        if not isinstance(self.mode, ChildBatchExecutionMode):
            raise TypeError(
                "child batch execution mode must be ChildBatchExecutionMode"
            )
        if type(self.executions) is not tuple or not self.executions:
            raise ValueError(
                "child batch execution requires non-empty executions"
            )
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
        mechanics = _sha(
            self.mechanics_identity_digest,
            "child batch mechanics identity_digest",
        )
        object.__setattr__(self, "mechanics_identity_digest", mechanics)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "execution_digest",
            canonical_digest({
                "schema": "noetrium.child-research-machine-batch-execution.v1",
                "request_digest": self.request_digest,
                "mode": self.mode.value,
                "children": tuple(
                    {
                        "machine_id": row.execution.machine_id,
                        "revision": row.execution.revision,
                        "status": row.execution.status.value,
                        "cut_digest": row.execution.cut.cut_digest,
                        "program_digest": row.link.child_program_digest,
                        "snapshot_ref": row.link.child_snapshot_ref,
                        "result_ref": row.link.child_result_ref,
                    }
                    for row in self.executions
                ),
                "evidence_digests": evidence,
                "mechanics_identity_digest": mechanics,
                "receipt": thaw_json(self.receipt),
            }),
        )

    @property
    def links(self):
        return tuple(row.link for row in self.executions)

    @property
    def results(self):
        return tuple(row.result for row in self.executions)


class ChildResearchMachineBatchExecutor:
    """Validate one logical ready set and project its child Machine cuts."""

    def __init__(
        self,
        mechanics: ChildResearchMachineBatchMechanicsPort,
    ) -> None:
        if not isinstance(mechanics, ChildResearchMachineBatchMechanicsPort):
            raise TypeError(
                "child batch executor requires ChildResearchMachineBatchMechanicsPort"
            )
        self._mechanics = mechanics
        require_sha256(
            mechanics.identity_digest,
            "child batch mechanics identity_digest",
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "executor": "child-research-machine-batch",
            "mechanics_identity_digest": self._mechanics.identity_digest,
        })

    def execute(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchExecution:
        if not isinstance(request, ChildResearchMachineBatchRequest):
            raise TypeError(
                "child batch executor requires ChildResearchMachineBatchRequest"
            )
        result = self._mechanics.execute_batch(request)
        if not isinstance(result, ChildResearchMachineBatchMechanicsResult):
            raise TypeError(
                "child batch mechanics must return "
                "ChildResearchMachineBatchMechanicsResult"
            )
        if result.request_digest != request.request_digest:
            raise ValueError("child batch mechanics request identity mismatch")
        if request.require_concurrent:
            if result.mode is not ChildBatchExecutionMode.CONCURRENT:
                raise ValueError(
                    "child batch requires concurrent mechanics"
                )
            if not result.evidence_digests:
                raise ValueError(
                    "concurrent child batch requires concurrency evidence"
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
                raise ValueError(
                    "child batch link parent identity mismatch"
                )
            if link.child_machine_id != expected.child_machine_id:
                raise ValueError(
                    "child batch link child identity mismatch"
                )

        return ChildResearchMachineBatchExecution(
            request_digest=request.request_digest,
            mode=result.mode,
            executions=result.executions,
            evidence_digests=result.evidence_digests,
            mechanics_identity_digest=self._mechanics.identity_digest,
            receipt=result.receipt,
        )


class BatchCapableRegisteredChildResearchMachineExecutor:
    """Compose ordinary registered-child execution with an independent batch seam."""

    def __init__(
        self,
        executor: RegisteredChildResearchMachineExecutor,
        mechanics: ChildResearchMachineBatchMechanicsPort,
    ) -> None:
        if not isinstance(executor, RegisteredChildResearchMachineExecutor):
            raise TypeError(
                "batch-capable child executor requires registered child executor"
            )
        if not isinstance(mechanics, ChildResearchMachineBatchMechanicsPort):
            raise TypeError(
                "batch-capable child executor requires child batch mechanics"
            )
        self._executor = executor
        self._batch = ChildResearchMachineBatchExecutor(mechanics)

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "executor": "batch-capable-registered-child-research-machine",
            "single_executor_identity_digest": self._executor.identity_digest,
            "batch_executor_identity_digest": self._batch.identity_digest,
        })

    def execute(
        self,
        request: ChildResearchMachineRequest,
    ) -> ChildResearchMachineExecution:
        return self._executor.execute(request)

    def step_once(
        self,
        request: ChildResearchMachineRequest,
    ) -> ChildResearchMachineExecution:
        return self._executor.step_once(request)

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchExecution:
        return self._batch.execute(request)


class ThreadPoolChildResearchBatchMechanics(
    ChildResearchMachineBatchMechanicsPort
):
    """Concurrent dispatch for independent child Machines.

    This provider owns only physical dispatch mechanics. Each child still
    commits to its ordinary ResearchProgramHost/MachineJournal authority.
    When a batch explicitly requires concurrency, the complete ready set must
    fit within max_workers; otherwise execution fails closed rather than
    silently degrading to a serial or partial schedule.
    """

    def __init__(
        self,
        executor: RegisteredChildResearchMachineExecutor,
        *,
        max_workers: int,
    ) -> None:
        if not isinstance(executor, RegisteredChildResearchMachineExecutor):
            raise TypeError(
                "thread-pool child batch mechanics requires registered child executor"
            )
        if type(max_workers) is not int or max_workers < 2:
            raise ValueError(
                "thread-pool child batch max_workers must be at least two"
            )
        self._executor = executor
        self._max_workers = max_workers

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "mechanics": "registered-thread-pool-child-research-batch",
            "version": 1,
            "max_workers": self._max_workers,
            "child_executor_identity_digest": self._executor.identity_digest,
        })

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchMechanicsResult:
        if not isinstance(request, ChildResearchMachineBatchRequest):
            raise TypeError(
                "thread-pool child batch mechanics requires typed batch request"
            )
        item_count = len(request.items)
        if item_count == 1:
            execution = self._executor.execute(request.items[0].request)
            return ChildResearchMachineBatchMechanicsResult(
                request_digest=request.request_digest,
                mode=ChildBatchExecutionMode.SERIAL,
                executions=(execution,),
                receipt={
                    "mechanics": "registered-thread-pool-child-research-batch",
                    "max_workers": self._max_workers,
                    "worker_count": 1,
                    "items": 1,
                },
            )
        if request.require_concurrent and item_count > self._max_workers:
            raise ValueError(
                "concurrent child batch ready set exceeds thread-pool worker capacity"
            )

        worker_count = min(self._max_workers, item_count)
        barrier = Barrier(item_count) if worker_count == item_count else None

        def run_item(index: int, item: ChildResearchMachineBatchItem):
            entered_ns = monotonic_ns()
            if barrier is not None:
                try:
                    barrier.wait(timeout=30.0)
                except BrokenBarrierError as exc:
                    raise RuntimeError(
                        "child batch concurrency barrier failed"
                    ) from exc
            dispatch_ns = monotonic_ns()
            execution = self._executor.execute(item.request)
            finished_ns = monotonic_ns()
            return (
                index,
                execution,
                {
                    "participant_id": item.participant_id,
                    "child_machine_id": item.request.child_machine_id,
                    "worker_entered_ns": entered_ns,
                    "dispatch_ns": dispatch_ns,
                    "finished_ns": finished_ns,
                },
            )

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="noetrium-child-batch",
        ) as pool:
            futures = tuple(
                pool.submit(run_item, index, item)
                for index, item in enumerate(request.items)
            )
            rows = tuple(future.result() for future in futures)

        ordered = tuple(sorted(rows, key=lambda row: row[0]))
        executions = tuple(row[1] for row in ordered)
        intervals = tuple(row[2] for row in ordered)
        mode = (
            ChildBatchExecutionMode.CONCURRENT
            if worker_count > 1
            else ChildBatchExecutionMode.SERIAL
        )
        evidence = ()
        if mode is ChildBatchExecutionMode.CONCURRENT:
            evidence = (
                canonical_digest({
                    "schema": "noetrium.child-batch-concurrency-evidence.v1",
                    "request_digest": request.request_digest,
                    "mechanics_identity_digest": self.identity_digest,
                    "worker_count": worker_count,
                    "full_ready_set_synchronized": barrier is not None,
                    "intervals": intervals,
                }),
            )
        return ChildResearchMachineBatchMechanicsResult(
            request_digest=request.request_digest,
            mode=mode,
            executions=executions,
            evidence_digests=evidence,
            receipt={
                "mechanics": "registered-thread-pool-child-research-batch",
                "max_workers": self._max_workers,
                "worker_count": worker_count,
                "items": item_count,
                "full_ready_set_synchronized": barrier is not None,
                "intervals": intervals,
            },
        )


class RegisteredSerialChildResearchBatchMechanics(
    ChildResearchMachineBatchMechanicsPort
):
    """Reference mechanics preserving the batch contract without concurrency.

    This adapter is useful when a method only needs ready-set identity/batching.
    Methods that require physical overlap must set require_concurrent=True and
    bind another mechanics provider; this serial reference then fails closed.
    """

    def __init__(
        self,
        executor: RegisteredChildResearchMachineExecutor,
    ) -> None:
        if not isinstance(executor, RegisteredChildResearchMachineExecutor):
            raise TypeError(
                "serial child batch mechanics requires registered child executor"
            )
        self._executor = executor

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "mechanics": "registered-serial-child-research-batch",
            "child_executor_identity_digest": self._executor.identity_digest,
        })

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchMechanicsResult:
        executions = tuple(
            self._executor.execute(item.request) for item in request.items
        )
        return ChildResearchMachineBatchMechanicsResult(
            request_digest=request.request_digest,
            mode=ChildBatchExecutionMode.SERIAL,
            executions=executions,
            receipt={
                "mechanics": "registered-serial-child-research-batch",
                "count": len(executions),
            },
        )


__all__ = [
    "BatchCapableRegisteredChildResearchMachineExecutor",
    "ChildBatchExecutionMode",

    "ChildResearchMachineBatchExecution",
    "ChildResearchMachineBatchExecutor",
    "ChildResearchMachineBatchItem",
    "ChildResearchMachineBatchPort",
    "ChildResearchMachineBatchMechanicsPort",
    "ChildResearchMachineBatchMechanicsResult",
    "ChildResearchMachineBatchRequest",
    "RegisteredSerialChildResearchBatchMechanics",
    "ThreadPoolChildResearchBatchMechanics",
]
