from __future__ import annotations

import time
from queue import Empty, Queue
from uuid import uuid4

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphControlRecord,
    ResearchGraphControlStorePort,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionReport,
    ResearchGraphExecutionStorePort,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlRecord,
    ResearchGraphNodeControlStorePort,
    ResearchGraphNode,
    ResearchGraphNodeExecutorPort,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    ResearchGraphPlan,
    ResearchGraphReconciliationRequired,
)
from noetrium_platform.research.execution.policy.api import ExecutionPriority


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
        self._scheduler_owner_id = (
            scheduler_owner_id
            or f"research-graph-scheduler:{uuid4().hex}"
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

        try:
            while pending or running:
                progressed = False

                for node_id in tuple(sorted(pending)):
                    node = pending[node_id]
                    blockers = tuple(
                        dependency
                        for dependency in node.depends_on_node_ids
                        if dependency in results
                        and results[dependency].state
                        in {
                            ResearchGraphNodeState.FAILED,
                            ResearchGraphNodeState.BLOCKED,
                        }
                    )
                    if not blockers:
                        continue
                    results[node_id] = ResearchGraphNodeResult(
                        node.node_id,
                        node.semantic_digest,
                        ResearchGraphNodeState.BLOCKED,
                        blocked_by_node_ids=blockers,
                    )
                    del pending[node_id]
                    progressed = True

                for node_id in tuple(sorted(pending)):
                    node = pending[node_id]
                    if not all(
                        dependency in results
                        and results[dependency].state
                        is ResearchGraphNodeState.SUCCEEDED
                        for dependency in node.depends_on_node_ids
                    ):
                        continue
                    running[node_id] = (node, submit(node))
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
        store.ensure_execution(execution_id, self._plan)
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
        debt_ids = snapshot.reconciliation_required_node_ids
        global_debt = tuple(
            node_id
            for node_id in debt_ids
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

        group = self._pool.open_orchestration_group(
            self._task_group_id or f"research-graph:{execution_id}",
            tenant_id=self._tenant_id,
            resource_id=f"research-graph:{self._plan.graph_id}",
            priority=self._priority,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        running: dict[str, tuple[ResearchGraphNode, object, str, int]] = {}
        renewal_interval_ns = max(1, self._lease_ns // 3)
        completion_queue: Queue[str] = Queue()

        def submit(node: ResearchGraphNode, attempt_id: str):
            def run(context, owned_node=node, owned_attempt_id=attempt_id):
                try:
                    store.mark_running(
                        execution_id,
                        owned_node.node_id,
                        attempt_id=owned_attempt_id,
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

            return group.submit(
                ExecutionSpec(
                    task_id=(
                        f"research-graph-node:{execution_id}:{node.node_id}"
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
                deadline=deadline,
            )

        def record_completion(node_id: str) -> None:
            node, handle, attempt_id, _next_renewal = running.pop(node_id)
            try:
                handle.result()
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
            except BaseException as exc:
                handle.cancel()
                failure = _reportable_failure(exc)
                description = describe_exception(failure)
                message = (
                    description.safe_message.strip()
                    or type(failure).__name__
                )
                current = store.snapshot(execution_id).node(node_id)
                live[node_id] = current
                if (
                    current.state is ResearchGraphLiveNodeState.RUNNING
                    and current.attempt_id == attempt_id
                    and current.lease_owner_id == self._scheduler_owner_id
                ):
                    current = store.mark_failed(
                        execution_id,
                        node.node_id,
                        attempt_id=attempt_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=time.time_ns(),
                        failure_type=type(failure).__name__,
                        failure_message=message,
                    )
                    live[node_id] = current
                    results[node_id] = ResearchGraphNodeResult(
                        node.node_id,
                        node.semantic_digest,
                        ResearchGraphNodeState.FAILED,
                        failure_type=type(failure).__name__,
                        failure_message=message,
                    )
                    return
                if current.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
                    reconciliation_required.add(node_id)
                    return
                node_control = node_control_store.node_control_state(
                    execution_id, node_id
                )
                if (
                    current.state is ResearchGraphLiveNodeState.PENDING
                    and node_control.phase is ResearchGraphNodeControlPhase.PAUSED
                ):
                    pending[node_id] = node
                    return
                if current.state is ResearchGraphLiveNodeState.CANCELLED:
                    results[node_id] = ResearchGraphNodeResult(
                        node.node_id,
                        node.semantic_digest,
                        ResearchGraphNodeState.CANCELLED,
                    )
                    return
                control = control_store.control_state(execution_id)
                if control.phase in {
                    ResearchGraphControlPhase.PAUSED,
                    ResearchGraphControlPhase.RECOVERY_REQUIRED,
                    ResearchGraphControlPhase.CANCELLED,
                }:
                    raise ResearchGraphControlHalt(control)
                raise

        try:
            while pending or running:
                current_control = control_store.control_state(execution_id)
                if current_control.phase in {
                    ResearchGraphControlPhase.PAUSED,
                    ResearchGraphControlPhase.RECOVERY_REQUIRED,
                    ResearchGraphControlPhase.CANCELLED,
                }:
                    for _node_id, (
                        _node,
                        handle,
                        _attempt_id,
                        _renewal,
                    ) in tuple(running.items()):
                        handle.cancel()
                    raise ResearchGraphControlHalt(current_control)
                draining = (
                    current_control.phase is ResearchGraphControlPhase.DRAINING
                )

                if deadline is not None and deadline.expired:
                    for _node_id, (_node, handle, _attempt_id, _renewal) in tuple(
                        running.items()
                    ):
                        handle.cancel()
                    raise TimeoutError(
                        "durable research graph execution deadline expired; "
                        "active leases will recover safely"
                    )

                progressed = False

                for node_id in tuple(sorted(pending)):
                    node = pending[node_id]
                    blockers = tuple(
                        dependency
                        for dependency in node.depends_on_node_ids
                        if dependency in results
                        and results[dependency].state
                        in {
                            ResearchGraphNodeState.FAILED,
                            ResearchGraphNodeState.BLOCKED,
                        }
                    )
                    if not blockers:
                        continue
                    record = store.mark_blocked(
                        execution_id,
                        node_id,
                        blocked_by_node_ids=blockers,
                    )
                    live[node_id] = record
                    results[node_id] = ResearchGraphNodeResult(
                        node.node_id,
                        node.semantic_digest,
                        ResearchGraphNodeState.BLOCKED,
                        blocked_by_node_ids=blockers,
                    )
                    del pending[node_id]
                    progressed = True

                now_ns = time.time_ns()
                if not draining:
                    for node_id in tuple(sorted(pending)):
                        node = pending[node_id]
                        node_control = node_control_store.node_control_state(
                            execution_id, node_id
                        )
                        if node_control.phase is ResearchGraphNodeControlPhase.CANCELLED:
                            current = store.snapshot(execution_id).node(node_id)
                            if current.state is not ResearchGraphLiveNodeState.CANCELLED:
                                raise ResearchGraphExecutionConflict(
                                    "cancelled node control disagrees with execution state"
                                )
                            live[node_id] = current
                            results[node_id] = ResearchGraphNodeResult(
                                node.node_id,
                                node.semantic_digest,
                                ResearchGraphNodeState.CANCELLED,
                            )
                            del pending[node_id]
                            progressed = True
                            continue
                        if node_control.phase is ResearchGraphNodeControlPhase.DRAINING:
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
                        if not all(
                            dependency in results
                            and results[dependency].state
                            is ResearchGraphNodeState.SUCCEEDED
                            for dependency in node.depends_on_node_ids
                        ):
                            continue
                        current = live[node_id]
                        if (
                            current.state is ResearchGraphLiveNodeState.RETRY_WAIT
                            and current.retry_not_before_ns is not None
                            and current.retry_not_before_ns > now_ns
                        ):
                            continue
                        if current.state is not ResearchGraphLiveNodeState.READY:
                            current = store.mark_ready(
                                execution_id,
                                node_id,
                                now_ns=now_ns,
                            )
                            live[node_id] = current
                        try:
                            claim = store.claim(
                                execution_id,
                                node_id,
                                owner_id=self._scheduler_owner_id,
                                now_ns=now_ns,
                                lease_expires_at_ns=now_ns + self._lease_ns,
                            )
                        except ResearchGraphExecutionConflict:
                            current_snapshot = store.snapshot(execution_id)
                            live[node_id] = current_snapshot.node(node_id)
                            raise
                        live[node_id] = claim
                        attempt_id = claim.attempt_id
                        if attempt_id is None:
                            raise RuntimeError(
                                "claimed research graph node lost attempt id"
                            )
                        handle = submit(node, attempt_id)
                        running[node_id] = (
                            node,
                            handle,
                            attempt_id,
                            now_ns + renewal_interval_ns,
                        )
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

                now_ns = time.time_ns()
                for node_id in tuple(sorted(running)):
                    node, handle, attempt_id, next_renewal = running[node_id]
                    if handle.done() or now_ns < next_renewal:
                        continue
                    current = store.snapshot(execution_id).node(node_id)
                    node_control = node_control_store.node_control_state(
                        execution_id, node_id
                    )
                    if (
                        current.state is not ResearchGraphLiveNodeState.RUNNING
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
                    renewed = store.renew_lease(
                        execution_id,
                        node_id,
                        attempt_id=attempt_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=now_ns,
                        lease_expires_at_ns=now_ns + self._lease_ns,
                    )
                    live[node_id] = renewed
                    running[node_id] = (
                        node,
                        handle,
                        attempt_id,
                        now_ns + renewal_interval_ns,
                    )

                if draining and not running:
                    paused = control_store.pause_if_quiescent(
                        execution_id,
                        expected_generation=current_control.generation,
                        now_ns=time.time_ns(),
                    )
                    raise ResearchGraphControlHalt(paused)

                if pending and not running and not progressed:
                    local_controls = tuple(
                        node_control_store.node_control_state(execution_id, node_id)
                        for node_id in sorted(pending)
                        if node_control_store.node_control_state(
                            execution_id, node_id
                        ).phase
                        in {
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
                    retry_times = tuple(
                        record.retry_not_before_ns
                        for node_id, record in live.items()
                        if node_id in pending
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
                                completed_id = completion_queue.get(
                                    timeout=wait_seconds
                                )
                            except Empty:
                                continue
                            if completed_id in running:
                                record_completion(completed_id)
                            continue
                    raise RuntimeError(
                        "durable research graph scheduler reached an "
                        "impossible dependency state"
                    )

                if not running:
                    continue

                wait_seconds = 0.05
                if running:
                    next_renewal_ns = min(
                        renewal
                        for _node, _handle, _attempt, renewal
                        in running.values()
                    )
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
            self._pool.close_orchestration_group(
                group,
                cancel_pending=deadline.expired if deadline is not None else False,
                deadline=deadline,
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
