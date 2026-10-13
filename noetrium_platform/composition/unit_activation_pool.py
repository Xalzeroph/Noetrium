from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from threading import Event, Lock
from time import monotonic_ns

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.api import ScientificExecutionControlPort
from noetrium_platform.foundation.kernel.kernel.unit_activation import (
    UnitActivationRuntime,
    UnitActivationExecution,
)
from noetrium_platform.foundation.kernel.kernel.unit_activation_batch import (
    UnitActivationBatchItem,
    UnitActivationBatchMechanicsPort,
    UnitActivationBatchMechanicsResult,
    UnitActivationBatchRequest,
)

from .research_execution_pool import ResearchExecutionPool


class PooledUnitActivationMechanics(
    UnitActivationBatchMechanicsPort
):
    """Bind concurrent Unit activation dispatch to the canonical execution pool.

    The logical ready set remains owned by the unit-activation-batch contract. This
    composition provider owns no worker pool and no capacity ledger: physical
    admission and execution are delegated to the shared ResearchExecutionPool.
    """

    def __init__(
        self,
        activation_runtime: UnitActivationRuntime,
        *,
        execution_pool: ResearchExecutionPool,
        execution_tenant_id: str | None = None,
        parent_control: ExecutionControlPort,
    ) -> None:
        if not isinstance(activation_runtime, UnitActivationRuntime):
            raise TypeError(
                "pooled Unit activation mechanics requires UnitActivationRuntime"
            )
        if not isinstance(execution_pool, ResearchExecutionPool):
            raise TypeError(
                "pooled Unit activation mechanics requires explicit ResearchExecutionPool"
            )
        if not isinstance(parent_control, ScientificExecutionControlPort):
            raise TypeError(
                "pooled Unit activation mechanics requires ScientificExecutionControlPort"
            )
        if execution_tenant_id is not None and (
            type(execution_tenant_id) is not str
            or not execution_tenant_id.strip()
        ):
            raise ValueError(
                "pooled Unit activation execution_tenant_id must be non-empty text or None"
            )
        self._activation_runtime = activation_runtime
        self._pool = execution_pool
        self._parent_control = parent_control
        self._execution_tenant_id = (
            None
            if execution_tenant_id is None
            else execution_tenant_id.strip()
        )
        self._identity_digest = canonical_digest({
            "mechanics": "pooled-unit-activation.v2",
            "resource_authority": "research-execution-pool/unit",
            "dispatch_contract": "authority-maximal-capacity-window-once",
            "activation_runtime_identity_digest": self._activation_runtime.identity_digest,
            "scientific_clock_start": "environment-ready-or-unit-worker-entry.v3",
        })

    @property
    def activation_runtime_identity_digest(self) -> str:
        """Stable identity of the exact UnitActivationRuntime this mechanics drives."""
        return self._activation_runtime.identity_digest

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @staticmethod
    def _task_id(
        index: int,
        item: UnitActivationBatchItem,
    ) -> str:
        return (
            f"unit-activation-batch:{index}:"
            f"{item.participant_id}:"
            f"{item.request.child_machine_id}"
        )

    def execute_batch(
        self,
        request: UnitActivationBatchRequest,
    ) -> UnitActivationBatchMechanicsResult:
        if not isinstance(request, UnitActivationBatchRequest):
            raise TypeError(
                "pooled Unit activation mechanics requires typed batch request"
            )
        self._parent_control.checkpoint()
        item_count = len(request.items)
        group = self._pool.open_machine_group(
            f"unit-activation-batch:{request.request_digest}",
            tenant_id=self._execution_tenant_id,
            resource_id=f"unit-activation-parent:{request.parent_machine_id}",
        )
        # Terminal results are indexed directly by immutable request ordinal.
        # Completion order is arbitrary; a final comparison sort would cost
        # O(N log N) despite all ordinals already being in [0, N).
        ordered_rows: list[
            tuple[UnitActivationExecution, dict[str, object]] | None
        ] = [None] * item_count
        execution_failure: BaseException | None = None
        completion_queue: Queue[int] = Queue()
        clock_started = Event()
        clock_start_lock = Lock()

        def start_scientific_time_once() -> None:
            # A batch's first *actual* worker entry is the scientific clock
            # barrier. No eager activation during resource preparation. The
            # accepted budget Authority remains the only source of clock truth;
            # this local one-shot guard only avoids N duplicate ledger reads
            # and simultaneous activation attempts for N concurrent children.
            if clock_started.is_set():
                return
            with clock_start_lock:
                if clock_started.is_set():
                    return
                if not self._parent_control.scientific_time_active:
                    self._parent_control.activate_scientific_time()
                clock_started.set()

        def pair(index: int, item: UnitActivationBatchItem):
            def run(context):
                entered_ns = monotonic_ns()
                try:
                    # Environment-backed trials activate at their readiness
                    # barrier before child dispatch. Pure computation has no
                    # environment boundary, so worker entry is the canonical
                    # fallback. Activation is idempotent but the explicit guard
                    # preserves one causal start event.
                    start_scientific_time_once()
                    self._parent_control.checkpoint()
                    context.checkpoint()
                    dispatch_ns = monotonic_ns()
                    execution = self._activation_runtime.execute(item.request)
                    context.checkpoint()
                    self._parent_control.checkpoint()
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

        initial_batch_size = 0
        refill_count = 0
        constructed_candidates = 0
        peak_pending_candidates = 0
        peak_submitted_handles = 0
        nonblocking_admission_calls = 0
        completion_waves = 0
        try:
            # Start the first worker without waiting for a global topology
            # projection. In particular a single child never needs a batch
            # window read. Policy limits are fixed for this pool lifetime and
            # are sampled lazily at the first *additional* ready submission.
            window_limit: int | None = None
            active = {}
            next_index = 0
            first_completion_observed = False
            # Only the not-yet-admitted prefix is cached. Failed transient
            # admission retries reuse the exact immutable spec/callable pair:
            # each child dispatch closure is constructed at most once.
            pending_pairs: dict[int, tuple[ExecutionSpec, Callable[..., object]]] = {}

            def candidate(index: int):
                nonlocal constructed_candidates, peak_pending_candidates
                existing = pending_pairs.get(index)
                if existing is not None:
                    return existing
                created = pair(index, request.items[index])
                pending_pairs[index] = created
                constructed_candidates += 1
                peak_pending_candidates = max(
                    peak_pending_candidates, len(pending_pairs),
                )
                return created

            def refill() -> None:
                nonlocal next_index
                nonlocal initial_batch_size
                nonlocal refill_count, window_limit
                nonlocal peak_submitted_handles, nonblocking_admission_calls
                while next_index < item_count:
                    if not active:
                        # A completely idle batch blocks for exactly one permit
                        # to guarantee progress. No speculative ready work is
                        # queued behind that permit.
                        index = next_index
                        spec, run = candidate(index)
                        handle = group.submit(spec, run)
                        pending_pairs.pop(index)
                        active[index] = handle
                        peak_submitted_handles = max(
                            peak_submitted_handles, len(active),
                        )
                        next_index += 1
                        if not first_completion_observed:
                            initial_batch_size += 1
                        else:
                            refill_count += 1
                        continue

                    if window_limit is None:
                        # Full admission topology snapshots enumerate global
                        # groups and sort their IDs. Never pay that cost per
                        # completion or before the first Unit starts running.
                        # This is only a static upper bound, not an admission.
                        admission = self._pool.machine_admission_snapshot()
                        blocking_lane = next(
                            lane for lane in admission.lanes
                            if lane.lane_kind is ExecutionLaneKind.BLOCKING_IO
                        )
                        window_limit = min(
                            admission.max_total_in_flight,
                            admission.max_in_flight_per_group,
                            admission.max_in_flight_per_tenant,
                            admission.max_in_flight_per_resource,
                            blocking_lane.max_in_flight,
                        )
                        if window_limit <= 0:
                            raise RuntimeError(
                                "machine admission has no blocking execution lane"
                            )

                    # Build no more than the original Authority's fixed
                    # policy ceiling less our own outstanding handles. Live
                    # capacity, cross-portfolio fairness, cancellation and
                    # permit fencing remain decided by try_submit_maximal_batch,
                    # never by this advisory read-only window.
                    #
                    # With N children and window W, exactly N task pairs are
                    # constructed and only O(W) unadmitted pairs are retained,
                    # even after arbitrarily many failed admission attempts.
                    # This avoids O(N^2) tail rebuilding and O(group_count)
                    # admission snapshot scans on each completion.
                    available = window_limit - len(active)
                    if available <= 0:
                        break
                    end = min(item_count, next_index + available)
                    ready = tuple(candidate(index) for index in range(next_index, end))
                    nonblocking_admission_calls += 1
                    admitted = group.try_submit_maximal_batch(ready)
                    admitted_count = len(admitted)
                    if admitted_count <= 0:
                        break
                    for offset, handle in enumerate(admitted):
                        index = next_index + offset
                        pending_pairs.pop(index)
                        active[index] = handle
                    next_index += admitted_count
                    peak_submitted_handles = max(
                        peak_submitted_handles, len(active),
                    )
                    if not first_completion_observed:
                        initial_batch_size += admitted_count
                    else:
                        refill_count += admitted_count

            refill()
            while active:
                completed_index = completion_queue.get()
                first_completion_observed = True
                completion_waves += 1
                # All completions already queued belong to this same
                # authoritative task group. Retire their handles before
                # recalculating admission: otherwise finished tasks count as
                # locally in-flight, spuriously shrinking the rolling window
                # and requiring one snapshot/refill for every terminal child.
                completed = [completed_index]
                while True:
                    try:
                        completed.append(completion_queue.get_nowait())
                    except Empty:
                        break
                for index in completed:
                    handle = active.pop(index)
                    ordinal, execution, interval = handle.result()
                    if ordinal != index or ordered_rows[index] is not None:
                        raise RuntimeError(
                            "unit pipeline completion ordinal drift or duplication"
                        )
                    ordered_rows[index] = (execution, interval)
                group.assert_healthy()
                refill()
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
        if constructed_candidates != item_count or pending_pairs:
            raise RuntimeError(
                "unit pipeline candidate projection did not converge exactly once"
            )
        if any(row is None for row in ordered_rows):
            raise RuntimeError(
                "unit pipeline completion cardinality differs from Unit request"
            )
        executions = tuple(
            row[0] for row in ordered_rows if row is not None
        )
        intervals = tuple(
            row[1] for row in ordered_rows if row is not None
        )
        evidence = (
            canonical_digest({
                "schema": "noetrium.unit-activation-batch-dispatch-evidence.v3",
                "request_digest": request.request_digest,
                "mechanics_identity_digest": self.identity_digest,
                "resource_authority": "research-execution-pool/unit",
                "dispatch_strategy": "authority-maximal-ready-prefix",
                "atomic_initial_admission": False,
                "initial_batch_size": initial_batch_size,
                "refill_count": refill_count,
                "constructed_candidates": constructed_candidates,
                "peak_pending_candidates": peak_pending_candidates,
                "peak_submitted_handles": peak_submitted_handles,
                "nonblocking_admission_calls": nonblocking_admission_calls,
                "completion_waves": completion_waves,
                "candidate_projection": "capacity-window-single-materialization.v1",
                "intervals": intervals,
            }),
        )
        return UnitActivationBatchMechanicsResult(
            request_digest=request.request_digest,
            executions=executions,
            evidence_digests=evidence,
            receipt={
                "mechanics": "pooled-unit-activation.v2",
                "resource_authority": "research-execution-pool/unit",
                "dispatch_strategy": "authority-maximal-ready-prefix",
                "atomic_initial_admission": False,
                "initial_batch_size": initial_batch_size,
                "refill_count": refill_count,
                "items": item_count,
                "constructed_candidates": constructed_candidates,
                "peak_pending_candidates": peak_pending_candidates,
                "peak_submitted_handles": peak_submitted_handles,
                "nonblocking_admission_calls": nonblocking_admission_calls,
                "completion_waves": completion_waves,
                "candidate_projection": "capacity-window-single-materialization.v1",
                "intervals": intervals,
            },
        )


__all__ = ["PooledUnitActivationMechanics"]
