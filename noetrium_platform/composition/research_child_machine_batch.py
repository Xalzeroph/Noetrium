from __future__ import annotations

from queue import Queue
from time import monotonic_ns

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.machines.child_machine import (
    ChildResearchMachineExecutor,
)
from noetrium_platform.research.execution.machines.child_machine_batch import (
    ChildResearchMachineBatchItem,
    ChildResearchMachineBatchMechanicsPort,
    ChildResearchMachineBatchMechanicsResult,
    ChildResearchMachineBatchRequest,
)

from .research_execution_pool import ResearchExecutionPool


class PooledChildResearchBatchMechanics(
    ChildResearchMachineBatchMechanicsPort
):
    """Bind concurrent child-Machine dispatch to the canonical execution pool.

    The logical ready set remains owned by the child-batch contract. This
    composition provider owns no worker pool and no capacity ledger: physical
    admission and execution are delegated to the shared ResearchExecutionPool.
    """

    def __init__(
        self,
        executor: ChildResearchMachineExecutor,
        *,
        execution_pool: ResearchExecutionPool,
    ) -> None:
        if not isinstance(executor, ChildResearchMachineExecutor):
            raise TypeError(
                "pooled child batch mechanics requires ChildResearchMachineExecutor"
            )
        if not isinstance(execution_pool, ResearchExecutionPool):
            raise TypeError(
                "pooled child batch mechanics requires explicit ResearchExecutionPool"
            )
        self._executor = executor
        self._pool = execution_pool
        self._identity_digest = canonical_digest({
            "mechanics": "pooled-child-research-batch",
            "resource_authority": "research-execution-pool/machine",
            "dispatch_contract": "bounded-rolling-window-ready-set",
            "child_executor_identity_digest": self._executor.identity_digest,
        })

    @property
    def child_executor_identity_digest(self) -> str:
        return self._executor.identity_digest

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @staticmethod
    def _task_id(
        index: int,
        item: ChildResearchMachineBatchItem,
    ) -> str:
        return (
            f"child-batch:{index}:"
            f"{item.participant_id}:"
            f"{item.request.child_machine_id}"
        )

    def execute_batch(
        self,
        request: ChildResearchMachineBatchRequest,
    ) -> ChildResearchMachineBatchMechanicsResult:
        if not isinstance(request, ChildResearchMachineBatchRequest):
            raise TypeError(
                "pooled child batch mechanics requires typed batch request"
            )
        item_count = len(request.items)
        group = self._pool.open_machine_group(
            f"child-batch:{request.request_digest}",
            resource_id=f"child-machine-parent:{request.parent_machine_id}",
        )
        rows = []
        execution_failure: BaseException | None = None
        completion_queue: Queue[int] = Queue()

        def pair(index: int, item: ChildResearchMachineBatchItem):
            def run(context):
                entered_ns = monotonic_ns()
                try:
                    context.checkpoint()
                    dispatch_ns = monotonic_ns()
                    execution = self._executor.execute(item.request)
                    context.checkpoint()
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
                finally:
                    completion_queue.put(index)

            return (
                ExecutionSpec(
                    task_id=self._task_id(index, item),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
            )

        width = request.dispatch_parallelism
        initial_batch_size = min(width, item_count)
        refill_count = item_count - initial_batch_size
        try:
            active = {}
            initial = tuple(
                pair(index, request.items[index])
                for index in range(initial_batch_size)
            )
            initial_handles = group.submit_atomic_batch(initial)
            active.update(
                (index, handle)
                for index, handle in enumerate(initial_handles)
            )
            next_index = initial_batch_size
            while active:
                completed_index = completion_queue.get()
                handle = active.pop(completed_index)
                rows.append(handle.result())
                group.assert_healthy()
                if next_index < item_count:
                    refill_handle = group.submit_atomic_batch(
                        (pair(next_index, request.items[next_index]),)
                    )[0]
                    active[next_index] = refill_handle
                    next_index += 1
        except BaseException as exc:
            execution_failure = exc

        close_failure: BaseException | None = None
        try:
            self._pool.close_machine_group(
                group,
                cancel_pending=execution_failure is not None,
            )
        except BaseException as exc:
            close_failure = exc

        if execution_failure is not None and close_failure is not None:
            raise ExceptionGroup(
                "child batch execution and resource convergence failed",
                [execution_failure, close_failure],
            )
        if execution_failure is not None:
            raise execution_failure
        if close_failure is not None:
            raise close_failure
        ordered = tuple(sorted(rows, key=lambda row: row[0]))
        executions = tuple(row[1] for row in ordered)
        intervals = tuple(row[2] for row in ordered)
        evidence = (
            canonical_digest({
                "schema": "noetrium.child-batch-dispatch-evidence.v2",
                "request_digest": request.request_digest,
                "mechanics_identity_digest": self.identity_digest,
                "resource_authority": "research-execution-pool/machine",
                "dispatch_strategy": "bounded-rolling-window",
                "atomic_initial_admission": True,
                "dispatch_parallelism": request.dispatch_parallelism,
                "initial_batch_size": initial_batch_size,
                "refill_count": refill_count,
                "intervals": intervals,
            }),
        )
        return ChildResearchMachineBatchMechanicsResult(
            request_digest=request.request_digest,
            dispatch_parallelism=request.dispatch_parallelism,
            executions=executions,
            evidence_digests=evidence,
            receipt={
                "mechanics": "pooled-child-research-batch",
                "resource_authority": "research-execution-pool/machine",
                "dispatch_strategy": "bounded-rolling-window",
                "atomic_initial_admission": True,
                "dispatch_parallelism": request.dispatch_parallelism,
                "initial_batch_size": initial_batch_size,
                "refill_count": refill_count,
                "items": item_count,
                "intervals": intervals,
            },
        )


__all__ = ["PooledChildResearchBatchMechanics"]
