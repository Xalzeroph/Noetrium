from __future__ import annotations

import time
from queue import Empty, Queue
from threading import RLock
from uuid import uuid4

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph_frontier import (
    ResearchGraphDependencyFrontier,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionPermitRejected,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphControlRecord,
    ResearchGraphControlStorePort,
    ResearchGraphClaimRecoveryPort,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionReport,
    ResearchGraphExecutionSnapshot,
    ResearchGraphExecutionStorePort,
    ResearchGraphLeaseRenewal,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlRecord,
    ResearchGraphNodeControlStorePort,
    ResearchGraphNodeExecutionRecord,
    ResearchGraphOwnerGenerationRecoveryPort,
    ResearchGraphNode,
    ResearchGraphNodeExecutorPort,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    ResearchGraphPlan,
    ResearchGraphReconciliationRequired,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionMode,
    ExecutionPriority,
)


def _reportable_failure(exc: BaseException) -> BaseException:
    def leaves(value: BaseException) -> list[BaseException]:
        if isinstance(value, BaseExceptionGroup):
            rows: list[BaseException] = []
            for child in value.exceptions:
                rows.extend(leaves(child))
            return rows
        return [value]

    rows = leaves(exc)
    if not rows:
        return exc
    unique = {(type(row), str(row)) for row in rows}
    if len(unique) == 1:
        return rows[0]
    return exc


class ResearchGraphControlHalt(RuntimeError):
    """Scheduler stopped at a durable graph-control boundary."""

    def __init__(self, control: ResearchGraphControlRecord) -> None:
        if type(control) is not ResearchGraphControlRecord:
            raise TypeError("research graph control halt requires typed control record")
        self.control = control
        super().__init__(
            "research graph scheduler halted by durable control: "
            f"{control.execution_id} -> {control.phase.value}"
        )


class ResearchGraphNodeControlHalt(RuntimeError):
    """Scheduler exhausted runnable work because selected nodes are locally controlled."""

    def __init__(self, controls: tuple[ResearchGraphNodeControlRecord, ...]) -> None:
        if type(controls) is not tuple or not controls or any(
            type(row) is not ResearchGraphNodeControlRecord for row in controls
        ):
            raise TypeError("research graph node control halt requires typed controls")
        ordered = tuple(sorted(controls, key=lambda row: row.node_id))
        self.controls = ordered
        super().__init__(
            "research graph scheduler halted by per-node control: "
            + ", ".join(f"{row.node_id}={row.phase.value}" for row in ordered)
        )


class _DurableAttemptBook:
    """Thread-safe local mirror of active durable graph attempts."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._attempts: dict[str, tuple[str, int]] = {}

    def current(self, node_id: str) -> tuple[str, int] | None:
        with self._lock:
            return self._attempts.get(node_id)

    def publish(
        self,
        node_id: str,
        attempt_id: str,
        next_renewal_ns: int,
    ) -> None:
        with self._lock:
            if node_id in self._attempts:
                raise RuntimeError(
                    f"research graph attempt published twice: {node_id}"
                )
            self._attempts[node_id] = (attempt_id, next_renewal_ns)

    def renew(
        self,
        node_id: str,
        attempt_id: str,
        next_renewal_ns: int,
    ) -> None:
        with self._lock:
            current = self._attempts.get(node_id)
            if current is None or current[0] != attempt_id:
                raise ResearchGraphExecutionConflict(
                    "research graph renewal lost local attempt identity"
                )
            self._attempts[node_id] = (attempt_id, next_renewal_ns)

    def drop(self, node_id: str) -> tuple[str, int] | None:
        with self._lock:
            return self._attempts.pop(node_id, None)


class ResearchGraphScheduler:
    """Single dependency-aware scheduler for all research orchestration.

    Scientific/domain execution remains delegated to ResearchGraphNodeExecutorPort.
    Resource capacity remains owned by ResearchExecutionPool.
    """

    def __init__(
        self,
        plan: ResearchGraphPlan,
        executor: ResearchGraphNodeExecutorPort,
        *,
        execution_pool: ResearchExecutionPool,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        task_group_id: str | None = None,
        execution_store: ResearchGraphExecutionStorePort | None = None,
        execution_id: str | None = None,
        lease_seconds: float = 30.0,
        scheduler_owner_id: str | None = None,
        selected_node_ids: tuple[str, ...] | None = None,
    ) -> None:
        if type(plan) is not ResearchGraphPlan:
            raise TypeError("research graph scheduler requires ResearchGraphPlan")
        if not isinstance(executor, ResearchGraphNodeExecutorPort):
            raise TypeError(
                "research graph scheduler executor must satisfy ResearchGraphNodeExecutorPort"
            )
        if not isinstance(execution_pool, ResearchExecutionPool):
            raise TypeError(
                "research graph scheduler requires explicit ResearchExecutionPool"
            )
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
        ):
            raise ValueError("research graph tenant_id must be non-empty when provided")
        if not isinstance(priority, ExecutionPriority):
            raise TypeError("research graph priority must be ExecutionPriority")
        if execution_store is not None and not isinstance(
            execution_store,
            ResearchGraphExecutionStorePort,
        ):
            raise TypeError(
                "research graph execution_store must satisfy "
                "ResearchGraphExecutionStorePort"
            )
        if execution_store is not None and (
            type(execution_id) is not str or not execution_id.strip()
        ):
            raise ValueError(
                "durable research graph scheduling requires execution_id"
            )
        if execution_store is None and execution_id is not None:
            raise ValueError(
                "research graph execution_id requires an execution_store"
            )
        if type(lease_seconds) not in {int, float} or lease_seconds <= 0:
            raise ValueError("research graph lease_seconds must be positive")
        if scheduler_owner_id is not None and (
            type(scheduler_owner_id) is not str
            or not scheduler_owner_id.strip()
        ):
            raise ValueError(
                "research graph scheduler_owner_id must be non-empty when provided"
            )
        known_node_ids = {node.node_id for node in plan.nodes}
        if selected_node_ids is None:
            selected = tuple(sorted(known_node_ids))
        else:
            if type(selected_node_ids) is not tuple or not selected_node_ids or any(
                type(node_id) is not str or not node_id.strip()
                for node_id in selected_node_ids
            ):
                raise TypeError(
                    "research graph selected_node_ids must be a non-empty text tuple"
                )
            selected = tuple(sorted(selected_node_ids))
            if len(selected) != len(set(selected)):
                raise ValueError("research graph selected_node_ids must be unique")
            unknown = tuple(sorted(set(selected) - known_node_ids))
            if unknown:
                raise ValueError(
                    f"research graph selection references unknown nodes: {unknown}"
                )
            selected_set = set(selected)
            missing_dependencies = tuple(
                sorted(
                    (node.node_id, dependency)
                    for node in plan.nodes
                    if node.node_id in selected_set
                    for dependency in node.depends_on_node_ids
                    if dependency not in selected_set
                )
            )
            if missing_dependencies:
                raise ValueError(
                    "research graph selection must be dependency-closed; "
                    f"missing={missing_dependencies}"
                )
        self._plan = plan
        self._executor = executor
        self._pool = execution_pool
        self._tenant_id = tenant_id
        self._priority = priority
        self._task_group_id = task_group_id
        self._execution_store = execution_store
        self._execution_id = execution_id
        self._lease_ns = max(1, int(float(lease_seconds) * 1_000_000_000))
        self._automatic_owner_generation = scheduler_owner_id is None
        self._scheduler_owner_id = (
            scheduler_owner_id
            or (
                "research-graph-scheduler:"
                f"{execution_pool.owner_generation_id}:{uuid4().hex}"
            )
        )
        self._selected_node_ids = selected
        self._closed = False

    @property
    def plan(self) -> ResearchGraphPlan:
        return self._plan

    def execute(
        self,
        *,
        deadline: Deadline | None = None,
    ) -> ResearchGraphExecutionReport:
        if self._closed:
            raise RuntimeError("research graph scheduler is closed")
        if self._execution_store is not None:
            return self._execute_durable(deadline=deadline)
        group = self._pool.open_orchestration_group(
            self._task_group_id
            or f"research-graph:{self._plan.graph_id}:{uuid4().hex}",
            tenant_id=self._tenant_id,
            resource_id=f"research-graph:{self._plan.graph_id}",
            priority=self._priority,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        selected = set(self._selected_node_ids)
        pending = {
            node.node_id: node
            for node in self._plan.nodes
            if node.node_id in selected
        }
        running: dict[str, tuple[ResearchGraphNode, object]] = {}
        results: dict[str, ResearchGraphNodeResult] = {}
        frontier = ResearchGraphDependencyFrontier(
            self._plan,
            selected_node_ids=self._selected_node_ids,
            terminal_results=results,
        )
        completion_queue: Queue[str] = Queue()

        def submit(node: ResearchGraphNode):
            def run(context, owned_node=node):
                try:
                    context.checkpoint()
                    self._executor.execute(
                        context,
                        owned_node,
                        deadline=deadline,
                    )
                    context.checkpoint()
                finally:
                    completion_queue.put(owned_node.node_id)

            return group.submit(
                ExecutionSpec(
                    task_id=f"research-graph-node:{self._plan.graph_id}:{node.node_id}",
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
                deadline=deadline,
            )

        def record_completion(node_id: str, *, timeout: float | None = None) -> None:
            node, handle = running.pop(node_id)
            try:
                handle.result(timeout=timeout)
                results[node_id] = ResearchGraphNodeResult(
                    node.node_id,
                    node.semantic_digest,
                    ResearchGraphNodeState.SUCCEEDED,
                )
                frontier.record_terminal(results[node_id])
            except BaseException as exc:
                handle.cancel()
                failure = _reportable_failure(exc)
                description = describe_exception(failure)
                results[node_id] = ResearchGraphNodeResult(
                    node.node_id,
                    node.semantic_digest,
                    ResearchGraphNodeState.FAILED,
                    failure_type=type(failure).__name__,
                    failure_message=(
                        description.safe_message.strip()
                        or type(failure).__name__
                    ),
                )
                frontier.record_terminal(results[node_id])

        try:
            while pending or running:
                progressed = False

                for node_id, blockers in frontier.blocked_nodes(set(pending)):
                    node = pending[node_id]
                    result = ResearchGraphNodeResult(
                        node.node_id,
                        node.semantic_digest,
                        ResearchGraphNodeState.BLOCKED,
                        blocked_by_node_ids=blockers,
                    )
                    results[node_id] = result
                    del pending[node_id]
                    frontier.record_terminal(result)
                    progressed = True

                for node_id in frontier.ready_node_ids(set(pending)):
                    node = pending[node_id]
                    handle = submit(node)
                    frontier.consume_ready(node_id)
                    running[node_id] = (node, handle)
                    del pending[node_id]
                    progressed = True

                completed: list[str] = []
                while True:
                    try:
                        completed_id = completion_queue.get_nowait()
                    except Empty:
                        break
                    if completed_id in running:
                        completed.append(completed_id)
                if completed:
                    for node_id in sorted(completed):
                        record_completion(node_id)
                    continue

                if pending and not running and not progressed:
                    raise RuntimeError(
                        "research graph scheduler reached an impossible dependency state"
                    )

                if not running:
                    continue

                if deadline is not None and deadline.expired:
                    for node_id in tuple(sorted(running)):
                        record_completion(node_id, timeout=0.0)
                    continue

                wait_timeout = (
                    None
                    if deadline is None
                    else max(0.0, deadline.remaining_seconds)
                )
                try:
                    completed_id = completion_queue.get(timeout=wait_timeout)
                except Empty:
                    for node_id in tuple(sorted(running)):
                        record_completion(node_id, timeout=0.0)
                    continue
                if completed_id in running:
                    record_completion(completed_id)

            return ResearchGraphExecutionReport(
                self._plan.graph_id,
                self._plan.graph_digest,
                self._plan.research_revision_digest,
                tuple(results[node_id] for node_id in sorted(results)),
            )
        finally:
            self._pool.close_orchestration_group(
                group,
                cancel_pending=deadline.expired if deadline is not None else False,
                deadline=deadline,
            )


    def _prepare_durable_execution(
        self,
        store: ResearchGraphExecutionStorePort,
        execution_id: str,
        *,
        now_ns: int,
    ) -> tuple[
        ResearchGraphExecutionSnapshot,
        ResearchGraphControlStorePort,
        ResearchGraphNodeControlStorePort,
    ]:
        store.ensure_execution(execution_id, self._plan)
        if (
            self._automatic_owner_generation
            and self._pool.can_recover_abandoned_owner_generations
            and isinstance(store, ResearchGraphOwnerGenerationRecoveryPort)
        ):
            # The managed local runtime holds the outer interprocess lock.
            # Therefore a different pool generation cannot still own live
            # in-process workers. Reclaim it immediately rather than waiting
            # for the lease TTL; RUNNING remains reconciliation-required.
            store.recover_abandoned_owner_generation(
                execution_id,
                current_owner_generation_id=self._pool.owner_generation_id,
                now_ns=now_ns,
            )
        snapshot = store.recover_expired(execution_id, now_ns=now_ns)
        if not isinstance(store, ResearchGraphControlStorePort):
            raise TypeError(
                "durable research graph scheduling requires graph control authority"
            )
        if not isinstance(store, ResearchGraphNodeControlStorePort):
            raise TypeError(
                "durable research graph scheduling requires per-node control authority"
            )
        control_store = store
        node_control_store = store
        control = control_store.control_state(execution_id)
        global_debt = tuple(
            node_id
            for node_id in snapshot.reconciliation_required_node_ids
            if node_control_store.node_control_state(
                execution_id, node_id
            ).phase is not ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
        )
        if global_debt:
            if control.phase is not ResearchGraphControlPhase.RECOVERY_REQUIRED:
                control = control_store.require_recovery(
                    execution_id,
                    expected_generation=control.generation,
                    now_ns=now_ns,
                )
            raise ResearchGraphControlHalt(control)
        if control.phase in {
            ResearchGraphControlPhase.PAUSED,
            ResearchGraphControlPhase.RECOVERY_REQUIRED,
            ResearchGraphControlPhase.CANCELLED,
        }:
            raise ResearchGraphControlHalt(control)
        if control.phase is ResearchGraphControlPhase.DRAINING:
            control = control_store.pause_if_quiescent(
                execution_id,
                expected_generation=control.generation,
                now_ns=now_ns,
            )
            raise ResearchGraphControlHalt(control)

        selected = set(self._selected_node_ids)
        active = tuple(
            node.node_id
            for node in snapshot.nodes
            if node.node_id in selected
            and node.state in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
            }
        )
        if active:
            raise ResearchGraphExecutionConflict(
                "research graph execution has active non-expired leases: "
                f"{active}"
            )
        return snapshot, control_store, node_control_store

    def _hydrate_durable_frontier(
        self,
        snapshot: ResearchGraphExecutionSnapshot,
    ) -> tuple[
        dict[str, ResearchGraphNodeExecutionRecord],
        dict[str, ResearchGraphNode],
        dict[str, ResearchGraphNodeResult],
        set[str],
        ResearchGraphDependencyFrontier,
    ]:
        selected = set(self._selected_node_ids)
        by_id = {node.node_id: node for node in self._plan.nodes}
        live = {node.node_id: node for node in snapshot.nodes}
        pending: dict[str, ResearchGraphNode] = {}
        results: dict[str, ResearchGraphNodeResult] = {}
        reconciliation_required = {
            node.node_id
            for node in snapshot.nodes
            if node.node_id in selected
            and node.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
        }

        for node_id, record in live.items():
            if node_id not in selected:
                continue
            node = by_id[node_id]
            if record.state in {
                ResearchGraphLiveNodeState.SUCCEEDED,
                ResearchGraphLiveNodeState.REUSED,
            }:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    node.semantic_digest,
                    ResearchGraphNodeState.SUCCEEDED,
                )
            elif record.state is ResearchGraphLiveNodeState.FAILED:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    node.semantic_digest,
                    ResearchGraphNodeState.FAILED,
                    failure_type=record.failure_type,
                    failure_message=record.failure_message,
                )
            elif record.state is ResearchGraphLiveNodeState.BLOCKED:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    node.semantic_digest,
                    ResearchGraphNodeState.BLOCKED,
                    blocked_by_node_ids=record.blocked_by_node_ids,
                )
            elif record.state is ResearchGraphLiveNodeState.CANCELLED:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    node.semantic_digest,
                    ResearchGraphNodeState.CANCELLED,
                )
            elif record.state in {
                ResearchGraphLiveNodeState.PENDING,
                ResearchGraphLiveNodeState.READY,
                ResearchGraphLiveNodeState.RETRY_WAIT,
            }:
                pending[node_id] = node

        frontier = ResearchGraphDependencyFrontier(
            self._plan,
            selected_node_ids=self._selected_node_ids,
            terminal_results=results,
        )
        return live, pending, results, reconciliation_required, frontier

    def _record_durable_completion(
        self,
        *,
        node_id: str,
        store: ResearchGraphExecutionStorePort,
        control_store: ResearchGraphControlStorePort,
        node_control_store: ResearchGraphNodeControlStorePort,
        execution_id: str,
        running: dict[str, tuple[ResearchGraphNode, object]],
        attempts: _DurableAttemptBook,
        live: dict[str, ResearchGraphNodeExecutionRecord],
        pending: dict[str, ResearchGraphNode],
        results: dict[str, ResearchGraphNodeResult],
        reconciliation_required: set[str],
        frontier: ResearchGraphDependencyFrontier,
    ) -> None:
        node, handle = running.pop(node_id)
        attempt = attempts.drop(node_id)
        attempt_id = None if attempt is None else attempt[0]
        try:
            handle.result()
            if attempt_id is None:
                raise ResearchGraphExecutionConflict(
                    "research graph task completed without durable claim"
                )
            record = store.mark_succeeded(
                execution_id,
                node.node_id,
                attempt_id=attempt_id,
                owner_id=self._scheduler_owner_id,
                now_ns=time.time_ns(),
            )
            live[node_id] = record
            results[node_id] = ResearchGraphNodeResult(
                node.node_id,
                node.semantic_digest,
                ResearchGraphNodeState.SUCCEEDED,
            )
            frontier.record_terminal(results[node_id])
            return
        except BaseException as exc:
            handle.cancel()
            original_failure = exc
            failure = _reportable_failure(exc)
            description = describe_exception(failure)
            message = description.safe_message.strip() or type(failure).__name__
            current = store.node_state(execution_id, node_id)
            live[node_id] = current

        if attempt_id is None:
            # The local attempt book is a renewal cache, not durable truth. A
            # claim may have committed immediately before the worker failed or
            # was descheduled. Recover that exact identity from the store.
            if (
                current.state
                in {
                    ResearchGraphLiveNodeState.CLAIMED,
                    ResearchGraphLiveNodeState.RUNNING,
                }
                and current.attempt_id is not None
                and current.lease_owner_id == self._scheduler_owner_id
            ):
                attempt_id = current.attempt_id
            else:
                node_control = node_control_store.node_control_state(
                    execution_id,
                    node_id,
                )
                control = control_store.control_state(execution_id)
                if (
                    current.state in {
                        ResearchGraphLiveNodeState.PENDING,
                        ResearchGraphLiveNodeState.READY,
                    }
                    and (
                        node_control.phase
                        is not ResearchGraphNodeControlPhase.ACTIVE
                        or control.phase is not ResearchGraphControlPhase.ACTIVE
                    )
                ):
                    pending[node_id] = node
                    frontier.restore_ready(node_id)
                    return
                if current.state is ResearchGraphLiveNodeState.CANCELLED:
                    results[node_id] = ResearchGraphNodeResult(
                        node.node_id,
                        node.semantic_digest,
                        ResearchGraphNodeState.CANCELLED,
                    )
                    frontier.record_terminal(results[node_id])
                    return
                raise ResearchGraphExecutionConflict(
                    "research graph worker failed before acquiring durable claim"
                ) from failure

        if (
            current.state is ResearchGraphLiveNodeState.CLAIMED
            and current.attempt_id == attempt_id
            and current.lease_owner_id == self._scheduler_owner_id
        ):
            if not isinstance(store, ResearchGraphClaimRecoveryPort):
                raise ResearchGraphExecutionConflict(
                    "research graph store cannot recover a never-started claim"
                ) from failure
            current = store.abandon_claim(
                execution_id,
                node.node_id,
                attempt_id=attempt_id,
                owner_id=self._scheduler_owner_id,
                now_ns=time.time_ns(),
            )
            live[node_id] = current
            pending[node_id] = node
            frontier.restore_ready(node_id)
            return

        if (
            current.state is ResearchGraphLiveNodeState.RUNNING
            and current.attempt_id == attempt_id
            and current.lease_owner_id == self._scheduler_owner_id
        ):
            failure_now_ns = time.time_ns()
            if (
                current.lease_expires_at_ns is not None
                and current.lease_expires_at_ns <= failure_now_ns
            ):
                if not isinstance(store, ResearchGraphClaimRecoveryPort):
                    raise ResearchGraphExecutionConflict(
                        "research graph store cannot recover an expired attempt"
                    ) from failure
                current = store.recover_expired_attempt(
                    execution_id,
                    node.node_id,
                    attempt_id=attempt_id,
                    owner_id=self._scheduler_owner_id,
                    now_ns=failure_now_ns,
                )
                live[node_id] = current
                if (
                    current.state
                    is not ResearchGraphLiveNodeState.RECONCILE_REQUIRED
                ):
                    raise ResearchGraphExecutionConflict(
                        "expired running attempt did not enter reconciliation"
                    ) from failure
                reconciliation_required.add(node_id)
                return

            try:
                current = store.mark_failed(
                    execution_id,
                    node.node_id,
                    attempt_id=attempt_id,
                    owner_id=self._scheduler_owner_id,
                    now_ns=failure_now_ns,
                    failure_type=type(failure).__name__,
                    failure_message=message,
                )
            except ResearchGraphExecutionConflict:
                # The lease may expire between the read above and the failure
                # CAS. Re-read exact durable truth; never weaken the lease
                # fence merely because completion arrived concurrently.
                refreshed = store.node_state(execution_id, node.node_id)
                recovery_now_ns = time.time_ns()
                if (
                    refreshed.state is ResearchGraphLiveNodeState.RUNNING
                    and refreshed.attempt_id == attempt_id
                    and refreshed.lease_owner_id == self._scheduler_owner_id
                    and refreshed.lease_expires_at_ns is not None
                    and refreshed.lease_expires_at_ns <= recovery_now_ns
                    and isinstance(store, ResearchGraphClaimRecoveryPort)
                ):
                    current = store.recover_expired_attempt(
                        execution_id,
                        node.node_id,
                        attempt_id=attempt_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=recovery_now_ns,
                    )
                    live[node_id] = current
                    reconciliation_required.add(node_id)
                    return
                raise

            live[node_id] = current
            results[node_id] = ResearchGraphNodeResult(
                node.node_id,
                node.semantic_digest,
                ResearchGraphNodeState.FAILED,
                failure_type=type(failure).__name__,
                failure_message=message,
            )
            frontier.record_terminal(results[node_id])
            node_control = node_control_store.node_control_state(
                execution_id,
                node_id,
            )
            if node_control.phase is ResearchGraphNodeControlPhase.DRAINING:
                node_control_store.pause_node_if_quiescent(
                    execution_id,
                    node_id,
                    expected_generation=node_control.generation,
                    now_ns=time.time_ns(),
                )
            return

        if current.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
            reconciliation_required.add(node_id)
            return

        node_control = node_control_store.node_control_state(
            execution_id,
            node_id,
        )
        if (
            current.state is ResearchGraphLiveNodeState.PENDING
            and node_control.phase is ResearchGraphNodeControlPhase.PAUSED
        ):
            pending[node_id] = node
            frontier.restore_ready(node_id)
            return
        if current.state is ResearchGraphLiveNodeState.CANCELLED:
            results[node_id] = ResearchGraphNodeResult(
                node.node_id,
                node.semantic_digest,
                ResearchGraphNodeState.CANCELLED,
            )
            frontier.record_terminal(results[node_id])
            return

        control = control_store.control_state(execution_id)
        if control.phase in {
            ResearchGraphControlPhase.PAUSED,
            ResearchGraphControlPhase.RECOVERY_REQUIRED,
            ResearchGraphControlPhase.CANCELLED,
        }:
            raise ResearchGraphControlHalt(control)
        raise original_failure

    def _renew_due_durable_leases(
        self,
        *,
        store: ResearchGraphExecutionStorePort,
        node_control_store: ResearchGraphNodeControlStorePort,
        execution_id: str,
        running: dict[str, tuple[ResearchGraphNode, object]],
        attempts: _DurableAttemptBook,
        live: dict[str, ResearchGraphNodeExecutionRecord],
        renewal_interval_ns: int,
        now_ns: int,
    ) -> None:
        due_attempts: dict[str, tuple[str, int]] = {}
        for node_id in tuple(sorted(running)):
            _node, handle = running[node_id]
            attempt = attempts.current(node_id)
            if handle.done() or attempt is None:
                continue
            attempt_id, next_renewal = attempt
            if now_ns >= next_renewal:
                due_attempts[node_id] = (attempt_id, next_renewal)

        if not due_attempts:
            return

        due_ids = tuple(sorted(due_attempts))
        current_rows = store.node_states(execution_id, due_ids)
        control_rows = node_control_store.node_control_states(
            execution_id,
            due_ids,
        )
        current_by_id = {row.node_id: row for row in current_rows}
        control_by_id = {row.node_id: row for row in control_rows}
        if (
            set(current_by_id) != set(due_ids)
            or set(control_by_id) != set(due_ids)
        ):
            raise ResearchGraphExecutionConflict(
                "lease-renewal batch read lost active nodes"
            )

        renewal_rows: list[ResearchGraphLeaseRenewal] = []
        renewal_node_ids: list[str] = []
        for node_id in due_ids:
            _node, handle = running[node_id]
            attempt_id, _next_renewal = due_attempts[node_id]
            current = current_by_id[node_id]
            node_control = control_by_id[node_id]
            if (
                current.state
                not in {
                    ResearchGraphLiveNodeState.CLAIMED,
                    ResearchGraphLiveNodeState.RUNNING,
                }
                or current.attempt_id != attempt_id
            ):
                if node_control.phase in {
                    ResearchGraphNodeControlPhase.PAUSED,
                    ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
                    ResearchGraphNodeControlPhase.CANCELLED,
                }:
                    handle.cancel()
                    continue
                raise ResearchGraphExecutionConflict(
                    "running scheduler attempt lost authoritative node state"
                )
            renewal_rows.append(
                ResearchGraphLeaseRenewal(
                    node_id,
                    attempt_id,
                    self._scheduler_owner_id,
                    now_ns + self._lease_ns,
                )
            )
            renewal_node_ids.append(node_id)

        if not renewal_rows:
            return

        renewed_rows = store.renew_leases(
            execution_id,
            tuple(renewal_rows),
            now_ns=now_ns,
        )
        renewed_by_node = {row.node_id: row for row in renewed_rows}
        if set(renewed_by_node) != set(renewal_node_ids):
            raise ResearchGraphExecutionConflict(
                "batch lease renewal returned a different node set"
            )
        for node_id in renewal_node_ids:
            attempt = attempts.current(node_id)
            if attempt is None:
                raise ResearchGraphExecutionConflict(
                    "renewed research graph node lost local attempt"
                )
            attempt_id, _next_renewal = attempt
            live[node_id] = renewed_by_node[node_id]
            attempts.renew(
                node_id,
                attempt_id,
                now_ns + renewal_interval_ns,
            )

    def _handle_durable_stall(
        self,
        *,
        execution_id: str,
        node_control_store: ResearchGraphNodeControlStorePort,
        pending: dict[str, ResearchGraphNode],
        running: dict[str, tuple[ResearchGraphNode, object]],
        reconciliation_required: set[str],
        frontier: ResearchGraphDependencyFrontier,
        live: dict[str, ResearchGraphNodeExecutionRecord],
        completion_queue: Queue[str],
        record_completion,
    ) -> bool:
        """Resolve a quiescent durable scheduler state or wait for retry eligibility.

        Returns True when the caller should continue the scheduling loop.
        Raises a typed control/reconciliation error for durable stop states.
        """
        local_control_ids = set(pending) | reconciliation_required
        local_control_tuple = tuple(sorted(local_control_ids))
        refreshed_controls = {
            row.node_id: row
            for row in node_control_store.node_control_states(
                execution_id,
                local_control_tuple,
            )
        }
        missing_local_controls = tuple(
            sorted(local_control_ids - set(refreshed_controls))
        )
        if missing_local_controls:
            raise ResearchGraphExecutionConflict(
                "research graph node control snapshot lost pending nodes: "
                f"{missing_local_controls}"
            )
        local_controls = tuple(
            refreshed_controls[node_id]
            for node_id in sorted(local_control_ids)
            if refreshed_controls[node_id].phase in {
                ResearchGraphNodeControlPhase.PAUSED,
                ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
            }
        )
        if local_controls:
            raise ResearchGraphNodeControlHalt(local_controls)
        if reconciliation_required:
            raise ResearchGraphReconciliationRequired(
                execution_id,
                tuple(sorted(reconciliation_required)),
            )

        ready_pending = set(frontier.ready_node_ids(set(pending)))
        retry_times = tuple(
            record.retry_not_before_ns
            for node_id, record in live.items()
            if node_id in ready_pending
            and record.state is ResearchGraphLiveNodeState.RETRY_WAIT
            and record.retry_not_before_ns is not None
        )
        if retry_times:
            delay = max(
                0.0,
                (min(retry_times) - time.time_ns()) / 1_000_000_000,
            )
            wait_seconds = min(0.05, delay)
            if wait_seconds > 0.0:
                try:
                    completed_id = completion_queue.get(timeout=wait_seconds)
                except Empty:
                    return True
                if completed_id in running:
                    record_completion(completed_id)
                return True
        raise RuntimeError(
            "durable research graph scheduler reached an impossible dependency state"
        )

    def _execute_durable(
        self,
        *,
        deadline: Deadline | None,
    ) -> ResearchGraphExecutionReport:
        store = self._execution_store
        execution_id = self._execution_id
        if store is None or execution_id is None:
            raise RuntimeError("durable graph scheduler is not fully bound")

        now_ns = time.time_ns()
        snapshot, control_store, node_control_store = (
            self._prepare_durable_execution(
                store,
                execution_id,
                now_ns=now_ns,
            )
        )
        (
            live,
            pending,
            results,
            reconciliation_required,
            frontier,
        ) = self._hydrate_durable_frontier(snapshot)

        base_group_id = (
            self._task_group_id or f"research-graph:{execution_id}"
        )
        fair_group = self._pool.open_orchestration_group(
            f"{base_group_id}:fair",
            tenant_id=self._tenant_id,
            resource_id=f"research-graph:{self._plan.graph_id}",
            priority=self._priority,
            admission_mode=AdmissionMode.BLOCK,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        try:
            opportunistic_group = self._pool.open_orchestration_group(
                f"{base_group_id}:opportunistic",
                tenant_id=self._tenant_id,
                resource_id=f"research-graph:{self._plan.graph_id}",
                priority=self._priority,
                admission_mode=AdmissionMode.REJECT,
                deadline=deadline,
                failure_policy=TaskFailurePolicy.COLLECT_ALL,
            )
        except BaseException:
            self._pool.close_orchestration_group(
                fair_group,
                cancel_pending=True,
                deadline=deadline,
            )
            raise

        running: dict[str, tuple[ResearchGraphNode, object]] = {}
        renewal_interval_ns = max(1, self._lease_ns // 3)
        attempts = _DurableAttemptBook()
        completion_queue: Queue[str] = Queue()
        submission_counts: dict[str, int] = {}

        def submit(
            node: ResearchGraphNode,
            *,
            block_for_capacity: bool,
        ):
            target_group = (
                fair_group if block_for_capacity else opportunistic_group
            )
            submission_number = submission_counts.get(node.node_id, 0) + 1
            submission_counts[node.node_id] = submission_number

            def run(context, owned_node=node):
                try:
                    claim_now_ns = time.time_ns()
                    claim = store.claim(
                        execution_id,
                        owned_node.node_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=claim_now_ns,
                        lease_expires_at_ns=claim_now_ns + self._lease_ns,
                    )
                    attempt_id = claim.attempt_id
                    if attempt_id is None:
                        raise RuntimeError(
                            "claimed research graph node lost attempt id"
                        )
                    # Publish the local renewal mirror immediately after the
                    # durable claim. The durable store remains authority; this
                    # mirror must never lag a committed claim into a false
                    # "never claimed" completion state.
                    attempts.publish(
                        owned_node.node_id,
                        attempt_id,
                        claim_now_ns,
                    )
                    store.mark_running(
                        execution_id,
                        owned_node.node_id,
                        attempt_id=attempt_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=time.time_ns(),
                    )
                    context.checkpoint()
                    self._executor.execute(
                        context,
                        owned_node,
                        deadline=deadline,
                    )
                    context.checkpoint()
                finally:
                    completion_queue.put(owned_node.node_id)

            return target_group.submit(
                ExecutionSpec(
                    task_id=(
                        f"research-graph-node:{execution_id}:{node.node_id}:"
                        f"submission:{submission_number}"
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
                deadline=deadline,
            )

        def record_completion(node_id: str) -> None:
            self._record_durable_completion(
                node_id=node_id,
                store=store,
                control_store=control_store,
                node_control_store=node_control_store,
                execution_id=execution_id,
                running=running,
                attempts=attempts,
                live=live,
                pending=pending,
                results=results,
                reconciliation_required=reconciliation_required,
                frontier=frontier,
            )

        try:
            while pending or running:
                current_control = control_store.control_state(execution_id)
                if current_control.phase in {
                    ResearchGraphControlPhase.PAUSED,
                    ResearchGraphControlPhase.RECOVERY_REQUIRED,
                    ResearchGraphControlPhase.CANCELLED,
                }:
                    for _node_id, (_node, handle) in tuple(running.items()):
                        handle.cancel()
                    raise ResearchGraphControlHalt(current_control)
                draining = (
                    current_control.phase is ResearchGraphControlPhase.DRAINING
                )

                if deadline is not None and deadline.expired:
                    for _node_id, (_node, handle) in tuple(
                        running.items()
                    ):
                        handle.cancel()
                    raise TimeoutError(
                        "durable research graph execution deadline expired; "
                        "active leases will recover safely"
                    )

                progressed = False

                blocked_rows = frontier.blocked_nodes(set(pending))
                if blocked_rows:
                    blocked_records = store.mark_blocked_many(
                        execution_id,
                        blocked_rows,
                    )
                    blocked_by_id = {
                        record.node_id: record
                        for record in blocked_records
                    }
                    expected_blocked_ids = {
                        node_id for node_id, _blockers in blocked_rows
                    }
                    if set(blocked_by_id) != expected_blocked_ids:
                        raise ResearchGraphExecutionConflict(
                            "blocked batch returned a different node set"
                        )
                    for node_id, blockers in blocked_rows:
                        node = pending[node_id]
                        live[node_id] = blocked_by_id[node_id]
                        result = ResearchGraphNodeResult(
                            node.node_id,
                            node.semantic_digest,
                            ResearchGraphNodeState.BLOCKED,
                            blocked_by_node_ids=blockers,
                        )
                        results[node_id] = result
                        del pending[node_id]
                        frontier.record_terminal(result)
                        progressed = True

                now_ns = time.time_ns()
                if not draining:
                    ready_node_ids = frontier.ready_node_ids(set(pending))
                    if ready_node_ids:
                        control_rows = node_control_store.node_control_states(
                            execution_id,
                            ready_node_ids,
                        )
                        node_controls = {
                            row.node_id: row for row in control_rows
                        }
                        if set(node_controls) != set(ready_node_ids):
                            raise ResearchGraphExecutionConflict(
                                "research graph node control batch lost ready nodes"
                            )
                    else:
                        node_controls = {}

                    cancelled_ids: list[str] = []
                    eligible_ids: list[str] = []
                    for node_id in ready_node_ids:
                        node_control = node_controls[node_id]
                        if (
                            node_control.phase
                            is ResearchGraphNodeControlPhase.CANCELLED
                        ):
                            cancelled_ids.append(node_id)
                            continue
                        if (
                            node_control.phase
                            is ResearchGraphNodeControlPhase.DRAINING
                        ):
                            node_control_store.pause_node_if_quiescent(
                                execution_id,
                                node_id,
                                expected_generation=node_control.generation,
                                now_ns=now_ns,
                            )
                            continue
                        if node_control.phase in {
                            ResearchGraphNodeControlPhase.PAUSED,
                            ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
                        }:
                            continue
                        current = live[node_id]
                        if (
                            current.state
                            is ResearchGraphLiveNodeState.RETRY_WAIT
                            and current.retry_not_before_ns is not None
                            and current.retry_not_before_ns > now_ns
                        ):
                            continue
                        eligible_ids.append(node_id)

                    if cancelled_ids:
                        cancelled_rows = store.node_states(
                            execution_id,
                            tuple(cancelled_ids),
                        )
                        cancelled_by_id = {
                            row.node_id: row for row in cancelled_rows
                        }
                        if set(cancelled_by_id) != set(cancelled_ids):
                            raise ResearchGraphExecutionConflict(
                                "cancelled node-state batch lost ready nodes"
                            )
                        for node_id in cancelled_ids:
                            current = cancelled_by_id[node_id]
                            if (
                                current.state
                                is not ResearchGraphLiveNodeState.CANCELLED
                            ):
                                raise ResearchGraphExecutionConflict(
                                    "cancelled node control disagrees with "
                                    "execution state"
                                )
                            node = pending[node_id]
                            live[node_id] = current
                            results[node_id] = ResearchGraphNodeResult(
                                node.node_id,
                                node.semantic_digest,
                                ResearchGraphNodeState.CANCELLED,
                            )
                            del pending[node_id]
                            frontier.record_terminal(results[node_id])
                            progressed = True

                    if eligible_ids:
                        ready_records = store.mark_ready_many(
                            execution_id,
                            tuple(eligible_ids),
                            now_ns=now_ns,
                        )
                        ready_by_id = {
                            row.node_id: row for row in ready_records
                        }
                        if set(ready_by_id) != set(eligible_ids):
                            raise ResearchGraphExecutionConflict(
                                "ready batch returned a different node set"
                            )
                        for node_id in eligible_ids:
                            live[node_id] = ready_by_id[node_id]

                    for node_id in eligible_ids:
                        node = pending[node_id]
                        try:
                            handle = submit(
                                node,
                                block_for_capacity=not running,
                            )
                        except ExecutionPermitRejected:
                            if not running:
                                raise ResearchGraphExecutionConflict(
                                    "fair research graph admission rejected a "
                                    "single-node request"
                                )
                            break
                        frontier.consume_ready(node_id)
                        running[node_id] = (node, handle)
                        del pending[node_id]
                        progressed = True

                # The scheduler remains the durable attempt owner until a
                # terminal result is committed. Renew before consuming local
                # completion notifications so a finished worker cannot lose its
                # lease merely while its result waits in the scheduler queue.
                now_ns = time.time_ns()
                self._renew_due_durable_leases(
                    store=store,
                    node_control_store=node_control_store,
                    execution_id=execution_id,
                    running=running,
                    attempts=attempts,
                    live=live,
                    renewal_interval_ns=renewal_interval_ns,
                    now_ns=now_ns,
                )

                completed: list[str] = []
                while True:
                    try:
                        completed_id = completion_queue.get_nowait()
                    except Empty:
                        break
                    if completed_id in running:
                        completed.append(completed_id)
                if completed:
                    for node_id in sorted(completed):
                        record_completion(node_id)
                    continue

                if draining and not running:
                    paused = control_store.pause_if_quiescent(
                        execution_id,
                        expected_generation=current_control.generation,
                        now_ns=time.time_ns(),
                    )
                    raise ResearchGraphControlHalt(paused)

                if pending and not running and not progressed:
                    if self._handle_durable_stall(
                        execution_id=execution_id,
                        node_control_store=node_control_store,
                        pending=pending,
                        running=running,
                        reconciliation_required=reconciliation_required,
                        frontier=frontier,
                        live=live,
                        completion_queue=completion_queue,
                        record_completion=record_completion,
                    ):
                        continue

                if not running:
                    continue

                wait_seconds = 0.05
                renewal_deadlines = tuple(
                    attempt[1]
                    for node_id in running
                    if (attempt := attempts.current(node_id)) is not None
                )
                if renewal_deadlines:
                    next_renewal_ns = min(renewal_deadlines)
                    wait_seconds = min(
                        wait_seconds,
                        max(
                            0.0,
                            (next_renewal_ns - time.time_ns())
                            / 1_000_000_000,
                        ),
                    )
                if deadline is not None:
                    wait_seconds = min(
                        wait_seconds,
                        max(0.0, deadline.remaining_seconds),
                    )
                try:
                    completed_id = completion_queue.get(timeout=wait_seconds)
                except Empty:
                    continue
                if completed_id in running:
                    record_completion(completed_id)

            if reconciliation_required:
                reconciliation_controls = {
                    row.node_id: row
                    for row in node_control_store.node_control_snapshot(execution_id)
                    if row.node_id in reconciliation_required
                }
                local_recovery = tuple(
                    reconciliation_controls[node_id]
                    for node_id in sorted(reconciliation_controls)
                    if reconciliation_controls[node_id].phase
                    is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
                )
                if len(local_recovery) == len(reconciliation_required):
                    raise ResearchGraphNodeControlHalt(local_recovery)
                raise ResearchGraphReconciliationRequired(
                    execution_id,
                    tuple(sorted(reconciliation_required)),
                )
            return ResearchGraphExecutionReport(
                self._plan.graph_id,
                self._plan.graph_digest,
                self._plan.research_revision_digest,
                tuple(results[node_id] for node_id in sorted(results)),
            )
        finally:
            close_errors: list[BaseException] = []
            for owned_group in (opportunistic_group, fair_group):
                try:
                    self._pool.close_orchestration_group(
                        owned_group,
                        cancel_pending=(
                            deadline.expired
                            if deadline is not None
                            else False
                        ),
                        deadline=deadline,
                    )
                except BaseException as exc:
                    close_errors.append(exc)
            if close_errors:
                raise ExceptionGroup(
                    "research graph resource groups failed to close",
                    close_errors,
                )

    def close(self, *, deadline: Deadline | None = None) -> None:
        if self._closed:
            return
        self._closed = True

    def __enter__(self) -> "ResearchGraphScheduler":
        if self._closed:
            raise RuntimeError("research graph scheduler is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = [
    "ResearchGraphControlHalt",
    "ResearchGraphNodeControlHalt",
    "ResearchGraphScheduler",
]
