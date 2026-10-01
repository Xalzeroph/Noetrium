from __future__ import annotations

from queue import Queue
from threading import Lock

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
)
from noetrium_platform.research.execution.workflow.composition.model_agent import (
    MethodAgentPanelExecutionPort,
    MethodAgentPanelInvocation,
)

from .research_execution_pool import ResearchExecutionPool


class PooledMethodAgentPanelExecution(MethodAgentPanelExecutionPort):
    """Rolling Method-panel fan-out over downstream capability-I/O mechanics.

    Panel membership, ordering and budget admission stay in Method semantics.
    The parent Method already executes in the Machine domain, so wrapper tasks
    must run downstream rather than recursively consuming Machine workers.
    Each wrapper may then wait on the independent model-I/O authority without
    nested same-domain admission.
    """

    def __init__(
        self,
        execution_pool: ResearchExecutionPool,
        *,
        execution_tenant_id: str | None = None,
    ) -> None:
        if not isinstance(execution_pool, ResearchExecutionPool):
            raise TypeError(
                "pooled Method panel execution requires ResearchExecutionPool"
            )
        if execution_tenant_id is not None and (
            type(execution_tenant_id) is not str
            or not execution_tenant_id.strip()
        ):
            raise ValueError(
                "Method panel execution tenant must be non-empty text or None"
            )
        self._pool = execution_pool
        self._tenant_id = (
            None
            if execution_tenant_id is None
            else execution_tenant_id.strip()
        )
        self._sequence_lock = Lock()
        self._sequence = 0

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._sequence += 1
            return self._sequence

    def execute(
        self,
        role: str,
        invocations: tuple[MethodAgentPanelInvocation, ...],
        request: MethodAgentRequest,
    ) -> tuple[tuple[int, MethodAgentResult], ...]:
        if type(role) is not str or not role.strip():
            raise ValueError("Method panel execution role must be non-empty")
        if type(invocations) is not tuple or not invocations:
            raise TypeError("Method panel execution requires invocations")
        if any(
            not isinstance(row, MethodAgentPanelInvocation)
            for row in invocations
        ):
            raise TypeError(
                "Method panel execution requires typed invocations"
            )
        expected_indexes = tuple(range(len(invocations)))
        indexes = tuple(row.member_index for row in invocations)
        if indexes != expected_indexes:
            raise ValueError(
                "Method panel invocation indexes must be contiguous and ordered"
            )
        if not isinstance(request, MethodAgentRequest):
            raise TypeError(
                "Method panel execution requires MethodAgentRequest"
            )

        sequence = self._next_sequence()
        invocation_digest = canonical_digest(
            {
                "schema": "noetrium.method-agent-panel-execution.v2",
                "role": role,
                "run_id": request.context.run_id,
                "trace_id": request.context.trace_id,
                "span_id": request.context.span_id,
                "decision_cycle_id": request.context.decision_cycle_id,
                "member_indexes": indexes,
                "sequence": sequence,
            }
        )
        group = self._pool.open_capability_io_group(
            f"method-panel:{invocation_digest}",
            tenant_id=(
                self._tenant_id
                or request.context.execution_tenant_id
            ),
            resource_id=f"method-panel:{role}",
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )

        snapshot = self._pool.capability_io_admission_snapshot()
        blocking_lane = next(
            (
                lane
                for lane in snapshot.lanes
                if lane.lane_kind is ExecutionLaneKind.BLOCKING_IO
            ),
            None,
        )
        if blocking_lane is None:
            self._pool.close_capability_io_group(
                group,
                cancel_pending=True,
            )
            raise RuntimeError(
                "capability-I/O admission has no blocking-I/O lane"
            )
        dispatch_parallelism = max(
            1,
            min(
                len(invocations),
                snapshot.max_total_in_flight,
                snapshot.max_in_flight_per_group,
                snapshot.max_in_flight_per_tenant,
                snapshot.max_in_flight_per_resource,
                blocking_lane.max_in_flight,
            ),
        )

        completion_queue: Queue[int] = Queue()
        started_lock = Lock()
        started: set[int] = set()
        active = {}
        rows: list[tuple[int, MethodAgentResult]] = []
        failures: list[tuple[int, BaseException]] = []
        infrastructure_failures: list[BaseException] = []

        def task(invocation: MethodAgentPanelInvocation):
            index = invocation.member_index

            def run(context):
                try:
                    context.checkpoint()
                    with started_lock:
                        started.add(index)
                    result = invocation.invoke()
                    if not isinstance(result, MethodAgentResult):
                        raise TypeError(
                            "Method panel invocation must return "
                            "MethodAgentResult"
                        )
                    return index, result
                finally:
                    completion_queue.put(index)

            return (
                ExecutionSpec(
                    task_id=(
                        f"method-panel-member:"
                        f"{invocation_digest[:20]}:{index}"
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
            )

        next_offset = 0

        def submit_initial() -> None:
            nonlocal next_offset
            initial = invocations[:dispatch_parallelism]
            handles = group.submit_atomic_batch(
                tuple(task(invocation) for invocation in initial)
            )
            active.update(
                {
                    invocation.member_index: handle
                    for invocation, handle in zip(
                        initial,
                        handles,
                        strict=True,
                    )
                }
            )
            next_offset = len(initial)

        def submit_next() -> None:
            nonlocal next_offset
            if next_offset >= len(invocations):
                return
            invocation = invocations[next_offset]
            handle = group.submit_atomic_batch(
                (task(invocation),)
            )[0]
            active[invocation.member_index] = handle
            next_offset += 1

        try:
            try:
                submit_initial()
            except BaseException as exc:
                infrastructure_failures.append(exc)

            while active:
                completed_index = completion_queue.get()
                handle = active.pop(completed_index)
                try:
                    row = handle.result()
                except BaseException as exc:
                    failures.append((completed_index, exc))
                else:
                    rows.append(row)

                if (
                    not infrastructure_failures
                    and next_offset < len(invocations)
                ):
                    try:
                        submit_next()
                    except BaseException as exc:
                        infrastructure_failures.append(exc)
        finally:
            try:
                self._pool.close_capability_io_group(
                    group,
                    cancel_pending=False,
                )
            except BaseException as exc:
                infrastructure_failures.append(exc)

        abort_failures: list[tuple[int, BaseException]] = []
        for invocation in invocations:
            with started_lock:
                was_started = invocation.member_index in started
            if was_started:
                continue
            try:
                invocation.abort()
            except BaseException as exc:
                abort_failures.append((invocation.member_index, exc))

        all_failures: list[BaseException] = [
            exc for _index, exc in sorted(failures, key=lambda row: row[0])
        ]
        all_failures.extend(infrastructure_failures)
        all_failures.extend(
            exc
            for _index, exc in sorted(
                abort_failures,
                key=lambda row: row[0],
            )
        )
        if all_failures:
            if len(all_failures) == 1:
                raise all_failures[0]
            raise ExceptionGroup(
                "Method panel execution failed",
                all_failures,
            )

        ordered = tuple(sorted(rows, key=lambda row: row[0]))
        if tuple(index for index, _result in ordered) != expected_indexes:
            raise RuntimeError(
                "Method panel execution lost or duplicated panel members"
            )
        return ordered


__all__ = ["PooledMethodAgentPanelExecution"]
