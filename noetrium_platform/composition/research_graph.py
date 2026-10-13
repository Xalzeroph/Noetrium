from __future__ import annotations

import time
import traceback
from heapq import heappop, heappush
from queue import Empty, Queue
from threading import RLock
from uuid import uuid4

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph_frontier import (
    ResearchGraphDependencyFrontier,
)
from noetrium_platform.composition.research_graph_dispatch_index import (
    ResearchGraphDispatchIndex,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    SchedulingCandidate,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    HeartbeatSpec,
    ExecutionPermitRejected,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
    TaskContextPort,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    exception_reference_projection,
)
from noetrium_platform.foundation.kernel.kernel.errors import (
    describe_exception,
    exception_leaves,
    redact_text,
)
from noetrium_platform.infrastructure.reliability.failure.api import (
    FailureReference,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphControlRecord,
    ResearchGraphControlStorePort,
    ResearchGraphClaimRecoveryPort,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionReport,
    ResearchGraphFailureProvenance,
    ResearchGraphExecutionSnapshot,
    ResearchGraphExecutionStorePort,
    ResearchGraphLeaseRenewal,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlRecord,
    ResearchGraphNodeControlStorePort,
    ResearchGraphNodeExecutionRecord,
    ResearchGraphOwnerGenerationRecoveryPort,
    ResearchGraphNodeExecutorPort,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    ResearchGraphReconciliationRequired,
    execution_graph_digest,
    execution_graph_id,
    execution_graph_research_revision_digest,
    execution_graph_index,
    execution_graph_vertices,
    execution_vertex_effectful,
    execution_vertex_id,
    execution_vertex_semantic_digest,
    execution_vertex_static_cost,
    validate_execution_graph,
)
from noetrium_platform.research.execution.policy.api import (
    ExecutionPriority,
)


def _reportable_failure(exc: BaseException) -> BaseException:
    rows = exception_leaves(exc)
    if not rows:
        return exc
    unique = {(type(row), str(row)) for row in rows}
    if len(unique) == 1:
        return rows[0]
    return exc


def _failure_provenance(exc: BaseException) -> ResearchGraphFailureProvenance:
    """Project graph failure metadata from the canonical failure/reference chain."""

    description = describe_exception(exc)
    frames = tuple(
        redact_text(row, max_chars=4096)
        for row in traceback.format_tb(exc.__traceback__)
        if row.strip()
    )
    cause_chain: list[str] = []
    failure_reference: FailureReference | None = None
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        current_description = describe_exception(current)
        if current is not exc:
            cause_chain.append(
                f"{current_description.qualified_type}: "
                f"{current_description.safe_message}"
            )
        candidate = getattr(current, "failure_reference", None)
        if failure_reference is None and isinstance(
            candidate,
            FailureReference,
        ):
            failure_reference = candidate
        current = (
            current.__cause__
            if current.__cause__ is not None
            else (None if current.__suppress_context__ else current.__context__)
        )

    if failure_reference is not None:
        failure_id = failure_reference.failure_id
        evidence_refs = failure_reference.graph_evidence_refs
        lower_refs = failure_reference.lower_refs
    else:
        # Non-materialized exceptions may still expose explicit typed refs.
        # The graph consumes the shared projection rather than importing or
        # guessing domain-specific exception attributes.
        refs = exception_reference_projection(exc)
        failure_id = None
        evidence_refs = tuple(dict.fromkeys((
            *(f"evidence:{value}" for value in refs.evidence_refs),
            *(f"artifact:{value}" for value in refs.artifact_refs),
        )))
        lower_refs = tuple(dict.fromkeys((
            *(f"request:{value}" for value in refs.request_refs),
            *(f"effect:{value}" for value in refs.effect_refs),
            *(f"state:{value}" for value in refs.state_refs),
            *(f"correlation:{value}" for value in refs.correlation_refs),
        )))

    return ResearchGraphFailureProvenance(
        qualified_type=description.qualified_type,
        error_digest=description.error_digest,
        safe_message=description.safe_message.strip() or type(exc).__name__,
        traceback_frames=frames,
        cause_chain=tuple(cause_chain),
        failure_id=failure_id,
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        lower_refs=tuple(dict.fromkeys(lower_refs)),
    )


class _AttemptTaskContext:
    """TaskContext proxy whose task identity is the durable graph attempt id."""

    def __init__(self, base: TaskContextPort, attempt_id: str) -> None:
        if type(attempt_id) is not str or not attempt_id.strip():
            raise ValueError("attempt task context requires durable attempt_id")
        self._base = base
        self._attempt_id = attempt_id

    @property
    def group_id(self):
        return self._base.group_id

    @property
    def task_id(self):
        return self._attempt_id

    @property
    def lane_kind(self):
        return self._base.lane_kind

    @property
    def deadline(self):
        return self._base.deadline

    @property
    def remaining_seconds(self):
        return self._base.remaining_seconds

    @property
    def cancelled(self):
        return self._base.cancelled

    @property
    def reason(self):
        return self._base.reason

    def wait(self, timeout: float | None = None) -> bool:
        return self._base.wait(timeout)

    def checkpoint(self) -> None:
        self._base.checkpoint()

    def subscribe_cancel(self, callback):
        # Durable attempt identity is the only override. Cancellation remains
        # owned by the original task/group authority and must not be dropped
        # when the attempt is projected across the adjacent graph boundary.
        return self._base.subscribe_cancel(callback)


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
    """Thread-safe local mirror with logarithmic renewal scheduling.

    Durable state remains authoritative. The heap is only a disposable index
    over the exact attempt identities in the mapping; stale heap entries are
    discarded lazily after renew or drop.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._attempts: dict[str, tuple[str, int, int]] = {}
        self._renewal_heap: list[tuple[int, str, str]] = []

    def current(self, node_id: str) -> tuple[str, int, int] | None:
        with self._lock:
            return self._attempts.get(node_id)

    def publish(
        self,
        node_id: str,
        attempt_id: str,
        next_renewal_ns: int,
        lease_expires_at_ns: int,
    ) -> None:
        if lease_expires_at_ns <= next_renewal_ns:
            raise ValueError("research graph lease must outlive its renewal point")
        with self._lock:
            if node_id in self._attempts:
                raise RuntimeError(
                    f"research graph attempt published twice: {node_id}"
                )
            self._attempts[node_id] = (attempt_id, next_renewal_ns, lease_expires_at_ns)
            heappush(
                self._renewal_heap,
                (next_renewal_ns, node_id, attempt_id),
            )

    def renew(
        self,
        node_id: str,
        attempt_id: str,
        next_renewal_ns: int,
        lease_expires_at_ns: int,
    ) -> None:
        if lease_expires_at_ns <= next_renewal_ns:
            raise ValueError("research graph lease must outlive its renewal point")
        with self._lock:
            current = self._attempts.get(node_id)
            if current is None or current[0] != attempt_id:
                raise ResearchGraphExecutionConflict(
                    "research graph renewal lost local attempt identity"
                )
            self._attempts[node_id] = (attempt_id, next_renewal_ns, lease_expires_at_ns)
            heappush(
                self._renewal_heap,
                (next_renewal_ns, node_id, attempt_id),
            )

    def _discard_stale_head_locked(self) -> None:
        while self._renewal_heap:
            next_ns, node_id, attempt_id = self._renewal_heap[0]
            current = self._attempts.get(node_id)
            if current is not None and current[:2] == (attempt_id, next_ns):
                return
            heappop(self._renewal_heap)

    def next_renewal_ns(self) -> int | None:
        with self._lock:
            self._discard_stale_head_locked()
            if not self._renewal_heap:
                return None
            return self._renewal_heap[0][0]

    def due(
        self,
        now_ns: int,
    ) -> tuple[tuple[str, str, int, int], ...]:
        with self._lock:
            due_rows: list[tuple[str, str, int, int]] = []
            popped: list[tuple[int, str, str]] = []
            self._discard_stale_head_locked()
            while self._renewal_heap and self._renewal_heap[0][0] <= now_ns:
                next_ns, node_id, attempt_id = heappop(self._renewal_heap)
                current = self._attempts.get(node_id)
                if current is None or current[:2] != (attempt_id, next_ns):
                    continue
                popped.append((next_ns, node_id, attempt_id))
                due_rows.append((node_id, attempt_id, next_ns, current[2]))
            for row in popped:
                heappush(self._renewal_heap, row)
            return tuple(due_rows)

    def snapshot(self) -> tuple[tuple[str, str, int, int], ...]:
        with self._lock:
            return tuple(
                (node_id, attempt_id, next_renewal_ns, lease_expires_at_ns)
                for node_id, (attempt_id, next_renewal_ns, lease_expires_at_ns)
                in sorted(self._attempts.items())
            )

    def drop(self, node_id: str) -> tuple[str, int, int] | None:
        with self._lock:
            return self._attempts.pop(node_id, None)


class ResearchGraphScheduler:
    """Single dependency-aware scheduler for all research orchestration.

    Scientific/domain execution remains delegated to ResearchGraphNodeExecutorPort.
    Resource capacity remains owned by ResearchExecutionPool.
    """

    def __init__(
        self,
        plan: NoetriumUnit,
        executor: ResearchGraphNodeExecutorPort,
        *,
        execution_pool: ResearchExecutionPool,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        task_group_id: str | None = None,
        execution_store: ResearchGraphExecutionStorePort,
        execution_id: str,
        lease_seconds: float = 30.0,
        scheduler_owner_id: str | None = None,
        selected_node_ids: tuple[str, ...] | None = None,
    ) -> None:
        if type(plan) is not NoetriumUnit:
            raise TypeError("research graph scheduler requires NoetriumUnit")
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
        if not isinstance(
            execution_store,
            ResearchGraphExecutionStorePort,
        ):
            raise TypeError(
                "research graph execution_store must satisfy "
                "ResearchGraphExecutionStorePort"
            )
        if type(execution_id) is not str or not execution_id.strip():
            raise ValueError(
                "research graph scheduling requires durable execution_id"
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
        if selected_node_ids is None:
            plan_index = execution_graph_index(plan)
            selected = tuple(execution_vertex_id(node) for node in plan_index.nodes)
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
            try:
                plan_index = execution_graph_index(plan, selected)
            except KeyError as exc:
                raise ValueError(
                    "research graph selection references unknown nodes"
                ) from exc
        self._plan = plan
        self._plan_index = plan_index
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
        # Exact structural critical-path work for the dependency-closed
        # execution projection. This is a disposable scheduling projection:
        # graph structure and static work remain the declared truth.
        self._critical_path_tail_work_by_node = self._critical_path_tail_work(plan_index)
        # Disposable online projection only. Durable truth remains the
        # Unit/Event + execution-store state; this cache may vanish on restart.
        # Value = (attempt_count, failure_count, total_scheduler_wall_ns).
        self._scheduling_history: dict[str, tuple[int, int, int]] = {}
        self._scheduling_ready_since: dict[str, float] = {}
        # The immutable per-Unit scheduling projection is cached by its exact
        # local evidence revision and deadline. Global service ordering is
        # NEVER cached: each admission still consults Scheduling Authority.
        # Values: (observed_history, deadline_monotonic, candidate).
        self._scheduling_candidates: dict[
            str,
            tuple[
                tuple[int, int, int] | None,
                float | None,
                SchedulingCandidate,
            ],
        ] = {}
        self._closed = False

    @property
    def plan(self) -> NoetriumUnit:
        return self._plan

    @staticmethod
    def _critical_path_tail_work(
        plan_index,
    ) -> dict[str, float]:
        """Return exact downstream critical work unlocked by each node.

        Let C(v) be total static work on the longest path beginning at v.
        A reverse topological pass computes C(v)=w(v)+max C(u). Scheduling,
        however, uses only tail(v)=C(v)-w(v): this is the dependency-unlock
        value. Independent sink jobs therefore have tail zero and retain
        shortest-work ordering, while a root that unlocks a long chain gains
        critical-path urgency without a tunable weight.

        Complexity is Theta(V + relation incidences) time and Theta(V) space.
        Hyperedges require no pairwise source-target expansion.
        """

        critical_total: dict[str, float] = {}
        critical_tail: dict[str, float] = {}
        # An m-source / n-target hyperedge is ONE dependency relation, not
        # m*n edges. Reverse topological order guarantees all target totals
        # are available before the first source is visited. Compute its tail
        # once and reuse it for every other source: O(V + source + target
        # incidences), without cross-product expansion.
        relation_tail: dict[int, float] = {}
        for node_id in reversed(plan_index.topological_order):
            downstream = 0.0
            for relation_index in plan_index.outgoing_relation_indices[node_id]:
                tail = relation_tail.get(relation_index)
                if tail is None:
                    targets = plan_index.relation_targets[relation_index]
                    tail = max(
                        (critical_total[target] for target in targets),
                        default=0.0,
                    )
                    relation_tail[relation_index] = tail
                if tail > downstream:
                    downstream = tail
            critical_tail[node_id] = downstream
            critical_total[node_id] = (
                float(
                    execution_vertex_static_cost(
                        plan_index.by_id[node_id]
                    )
                )
                + downstream
            )
        return critical_tail

    def _scheduling_candidate(
        self,
        node: NoetriumUnit,
        *,
        deadline: Deadline | None,
    ) -> SchedulingCandidate:
        """Project graph-local evidence into the one global scheduling law."""

        semantic_digest = execution_vertex_semantic_digest(node)
        node_id = execution_vertex_id(node)
        observed = self._scheduling_history.get(semantic_digest)
        deadline_monotonic = (
            None if deadline is None else float(deadline.monotonic_deadline)
        )
        cached = self._scheduling_candidates.get(node_id)
        if (
            cached is not None
            and cached[0] == observed
            and cached[1] == deadline_monotonic
        ):
            return cached[2]

        static_cost = execution_vertex_static_cost(node)
        if observed is None:
            attempts = 0
            failures = 0
            estimated_service_seconds = None
            expected_failure_waste_seconds = 0.0
        else:
            attempts, failures, total_wall_ns = observed
            estimated_service_seconds = (
                float(total_wall_ns) / float(attempts) / 1_000_000_000.0
            )
            expected_failure_waste_seconds = (
                estimated_service_seconds
                * (float(failures) / float(attempts))
            )
        ready_since = self._scheduling_ready_since.setdefault(
            semantic_digest,
            time.monotonic(),
        )
        candidate = SchedulingCandidate(
            ticket=int(semantic_digest, 16),
            group_id=semantic_digest,
            priority=self._priority,
            enqueued_monotonic=ready_since,
            tenant_id=self._tenant_id,
            speculation_rank=1 if execution_vertex_effectful(node) else 0,
            critical_path_tail_work=self._critical_path_tail_work_by_node[
                node_id
            ],
            expected_waste_cost=expected_failure_waste_seconds,
            estimated_service_seconds=estimated_service_seconds,
            estimated_service_cost=float(static_cost),
            deadline_monotonic=deadline_monotonic,
            deterministic_tiebreak=int(semantic_digest, 16),
        )
        self._scheduling_candidates[node_id] = (
            observed, deadline_monotonic, candidate,
        )
        return candidate

    def _observe_scheduling_attempt(
        self,
        node: NoetriumUnit,
        *,
        started_ns: int,
        failed: bool,
    ) -> None:
        semantic_digest = execution_vertex_semantic_digest(node)
        wall_ns = max(1, time.time_ns() - started_ns)
        attempts, failures, total_wall_ns = self._scheduling_history.get(
            semantic_digest,
            (0, 0, 0),
        )
        self._scheduling_history[semantic_digest] = (
            attempts + 1,
            failures + int(failed),
            total_wall_ns + wall_ns,
        )

    def execute(
        self,
        *,
        deadline: Deadline | None = None,
    ) -> ResearchGraphExecutionReport:
        if self._closed:
            raise RuntimeError("research graph scheduler is closed")
        return self._execute_durable(deadline=deadline)


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
        store.ensure_execution_identity(execution_id, self._plan)
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
        dict[str, NoetriumUnit],
        dict[str, ResearchGraphNodeResult],
        set[str],
        ResearchGraphDependencyFrontier,
    ]:
        selected = set(self._selected_node_ids)
        by_id = self._plan_index.by_id
        live = {node.node_id: node for node in snapshot.nodes}
        pending: dict[str, NoetriumUnit] = {}
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
                    execution_vertex_semantic_digest(node),
                    ResearchGraphNodeState.SUCCEEDED,
                )
            elif record.state is ResearchGraphLiveNodeState.FAILED:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    execution_vertex_semantic_digest(node),
                    ResearchGraphNodeState.FAILED,
                    failure_type=record.failure_type,
                    failure_message=record.failure_message,
                    failure_provenance=record.failure_provenance,
                )
            elif record.state is ResearchGraphLiveNodeState.BLOCKED:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    execution_vertex_semantic_digest(node),
                    ResearchGraphNodeState.BLOCKED,
                    blocked_by_node_ids=record.blocked_by_node_ids,
                )
            elif record.state is ResearchGraphLiveNodeState.CANCELLED:
                results[node_id] = ResearchGraphNodeResult(
                    node_id,
                    execution_vertex_semantic_digest(node),
                    ResearchGraphNodeState.CANCELLED,
                )
            elif record.state in {
                ResearchGraphLiveNodeState.PENDING,
                ResearchGraphLiveNodeState.READY,
                ResearchGraphLiveNodeState.RETRY_WAIT,
            }:
                pending[node_id] = node

        for node_id in selected:
            if node_id not in live:
                pending[node_id] = by_id[node_id]

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
        running: dict[str, tuple[NoetriumUnit, object, int]],
        attempts: _DurableAttemptBook,
        live: dict[str, ResearchGraphNodeExecutionRecord],
        pending: dict[str, NoetriumUnit],
        results: dict[str, ResearchGraphNodeResult],
        reconciliation_required: set[str],
        frontier: ResearchGraphDependencyFrontier,
    ) -> None:
        node, handle, started_ns = running.pop(node_id)
        # Keep the local lease-renewal identity live until the durable terminal
        # transition commits.  A completed worker is still owned work while
        # mark_succeeded/mark_failed/recovery is waiting on control-plane I/O.
        # Dropping it before the commit lets an unrelated scheduler stall expire
        # otherwise healthy RUNNING nodes during a control-plane stall.
        attempt = attempts.current(node_id)
        attempt_id = None if attempt is None else attempt[0]
        try:
            handle.result()
        except BaseException as exc:
            self._observe_scheduling_attempt(
                node,
                started_ns=started_ns,
                failed=True,
            )
            handle.cancel()
            original_failure = exc
            __import__("traceback").print_exception(exc)
            failure = _reportable_failure(exc)
            description = describe_exception(failure)
            message = description.safe_message.strip() or type(failure).__name__
            current = store.node_state(execution_id, node_id)
            live[node_id] = current
        else:
            self._observe_scheduling_attempt(
                node,
                started_ns=started_ns,
                failed=False,
            )
            if attempt_id is None:
                raise ResearchGraphExecutionConflict(
                    "research graph task completed without durable claim"
                )
            record = store.mark_succeeded(
                execution_id,
                execution_vertex_id(node),
                attempt_id=attempt_id,
                owner_id=self._scheduler_owner_id,
                now_ns=time.time_ns(),
            )
            live[node_id] = record
            attempts.drop(node_id)
            results[node_id] = ResearchGraphNodeResult(
                execution_vertex_id(node),
                execution_vertex_semantic_digest(node),
                ResearchGraphNodeState.SUCCEEDED,
            )
            frontier.record_terminal(results[node_id])
            return

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
                        execution_vertex_id(node),
                        execution_vertex_semantic_digest(node),
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
                execution_vertex_id(node),
                attempt_id=attempt_id,
                owner_id=self._scheduler_owner_id,
                now_ns=time.time_ns(),
            )
            live[node_id] = current
            attempts.drop(node_id)
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
                    execution_vertex_id(node),
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
                attempts.drop(node_id)
                reconciliation_required.add(node_id)
                return

            try:
                current = store.mark_failed(
                    execution_id,
                    execution_vertex_id(node),
                    attempt_id=attempt_id,
                    owner_id=self._scheduler_owner_id,
                    now_ns=failure_now_ns,
                    failure_type=type(failure).__name__,
                    failure_message=message,
                    failure_provenance=_failure_provenance(failure),
                )
            except ResearchGraphExecutionConflict:
                # The lease may expire between the read above and the failure
                # CAS. Re-read exact durable truth; never weaken the lease
                # fence merely because completion arrived concurrently.
                refreshed = store.node_state(execution_id, execution_vertex_id(node))
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
                        execution_vertex_id(node),
                        attempt_id=attempt_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=recovery_now_ns,
                    )
                    live[node_id] = current
                    attempts.drop(node_id)
                    reconciliation_required.add(node_id)
                    return
                raise

            live[node_id] = current
            attempts.drop(node_id)
            results[node_id] = ResearchGraphNodeResult(
                execution_vertex_id(node),
                execution_vertex_semantic_digest(node),
                ResearchGraphNodeState.FAILED,
                failure_type=current.failure_type,
                failure_message=current.failure_message,
                failure_provenance=current.failure_provenance,
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
            attempts.drop(node_id)
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
            attempts.drop(node_id)
            pending[node_id] = node
            frontier.restore_ready(node_id)
            return
        if current.state is ResearchGraphLiveNodeState.CANCELLED:
            results[node_id] = ResearchGraphNodeResult(
                execution_vertex_id(node),
                execution_vertex_semantic_digest(node),
                ResearchGraphNodeState.CANCELLED,
            )
            attempts.drop(node_id)
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
        execution_id: str,
        attempts: _DurableAttemptBook,
        renewal_interval_ns: int,
        now_ns: int,
    ) -> None:
        due_attempts = {
            node_id: (attempt_id, next_renewal, lease_expires_at_ns)
            for node_id, attempt_id, next_renewal, lease_expires_at_ns
            in attempts.due(now_ns)
        }
        if not due_attempts:
            return

        def renew_batch(
            selected: dict[str, tuple[str, int, int]],
            *,
            renewal_now_ns: int,
        ) -> tuple[str, ...]:
            # Renewal reaches the authoritative writer before diagnostic reads.
            # The store's priority transaction prevents ordinary graph writes
            # from barging ahead once this liveness-critical write is waiting.
            rows = tuple(
                ResearchGraphLeaseRenewal(
                    node_id,
                    selected[node_id][0],
                    self._scheduler_owner_id,
                    renewal_now_ns + self._lease_ns,
                )
                for node_id in sorted(selected)
            )
            earliest_expiry_ns = min(row[2] for row in selected.values())
            # A periodic tick can lag a claim-specific renewal point by one
            # interval. Subtracting that interval again expires valid ownership
            # near 2/3 TTL. Bound writer admission by the actual lease expiry;
            # the durable store still owns attempt/owner/expiry fencing.
            safety_deadline_ns = earliest_expiry_ns
            wait_timeout_seconds = (
                safety_deadline_ns - renewal_now_ns
            ) / 1_000_000_000
            if wait_timeout_seconds <= 0:
                raise ResearchGraphExecutionConflict(
                    "research graph lease renewal safety horizon exhausted"
                )
            renewed = store.renew_leases(
                execution_id,
                rows,
                now_ns=renewal_now_ns,
                wait_timeout_seconds=wait_timeout_seconds,
            )
            renewed_by_node = {row.node_id: row for row in renewed}
            node_ids = tuple(row.node_id for row in rows)
            if set(renewed_by_node) != set(node_ids):
                raise ResearchGraphExecutionConflict(
                    "batch lease renewal returned a different node set"
                )
            return node_ids

        renewal_now_ns = time.time_ns()
        selected = due_attempts
        while True:
            try:
                renewal_node_ids = renew_batch(
                    selected,
                    renewal_now_ns=renewal_now_ns,
                )
                break
            except ResearchGraphExecutionConflict as primary:
                # Any number of terminal transitions may commit between the
                # heartbeat snapshot, writer admission and a filtered retry.
                # Re-read durable truth and monotonically shrink the active set.
                # If the set does not shrink, this was not a benign terminal
                # race: owner/attempt fencing wins and the conflict is fatal.
                surviving: dict[str, tuple[str, int, int]] = {}
                for node_id, row in selected.items():
                    attempt_id, _next_renewal, _lease_expires_at_ns = row
                    local = attempts.current(node_id)
                    current = store.node_state(execution_id, node_id)
                    if current.state not in {
                        ResearchGraphLiveNodeState.CLAIMED,
                        ResearchGraphLiveNodeState.RUNNING,
                    }:
                        if local is not None and local[0] == attempt_id:
                            attempts.drop(node_id)
                        continue
                    if (
                        local is None
                        or local[0] != attempt_id
                        or current.attempt_id != attempt_id
                        or current.lease_owner_id != self._scheduler_owner_id
                    ):
                        raise primary
                    surviving[node_id] = row
                if not surviving:
                    return
                if set(surviving) == set(selected):
                    raise primary
                selected = surviving
                renewal_now_ns = time.time_ns()

        for node_id in renewal_node_ids:
            attempt = attempts.current(node_id)
            if attempt is None:
                # A concurrent terminal commit may have retired the local
                # identity after the renewal committed.  Durable terminal truth
                # wins and no further local bookkeeping is required.
                continue
            attempt_id, _next_renewal, _lease_expires_at_ns = attempt
            if attempt_id != selected[node_id][0]:
                raise ResearchGraphExecutionConflict(
                    "renewed research graph node changed local attempt identity"
                )
            attempts.renew(
                node_id,
                attempt_id,
                renewal_now_ns + renewal_interval_ns,
                renewal_now_ns + self._lease_ns,
            )

    def _handle_durable_stall(
        self,
        *,
        execution_id: str,
        node_control_store: ResearchGraphNodeControlStorePort,
        pending: dict[str, NoetriumUnit],
        running: dict[str, tuple[NoetriumUnit, object, int]],
        reconciliation_required: set[str],
        frontier: ResearchGraphDependencyFrontier,
        dispatch_index: ResearchGraphDispatchIndex,
        live: dict[str, ResearchGraphNodeExecutionRecord],
        completion_queue: Queue[tuple[str, str]],
        record_completion,
    ) -> bool:
        """Resolve a quiescent scheduler without rescanning the Ready frontier.

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

        # Quiescence has no running worker from which completion can arrive.
        # Dependency truth was already emitted as a one-time event into the
        # index; never rebuild a full Ready enumeration to diagnose it.
        if not (
            dispatch_index.has_indexed
            or dispatch_index.parked_ids
        ):
            raise RuntimeError(
                "durable research graph scheduler reached an impossible "
                "dependency state"
            )
        now_ns = time.time_ns()
        next_retry_ns = dispatch_index.next_retry_ns()
        delay = 0.25  # Bound for external SQLite control/admission changes.
        if next_retry_ns is not None:
            delay = min(
                delay,
                max(0.0, (next_retry_ns - now_ns) / 1_000_000_000),
            )
        if delay > 0:
            try:
                event_kind, event_node_id = completion_queue.get(
                    timeout=delay
                )
            except Empty:
                return True
            if event_kind == "completed" and event_node_id in running:
                record_completion(event_node_id)
        return True

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
            resource_id=f"research-graph:{execution_graph_id(self._plan)}",
            priority=self._priority,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        try:
            opportunistic_group = self._pool.open_orchestration_group(
                f"{base_group_id}:opportunistic",
                tenant_id=self._tenant_id,
                resource_id=f"research-graph:{execution_graph_id(self._plan)}",
                priority=self._priority,
                admission_queue_wait_timeout_seconds=0.0,
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

        # Fair/opportunistic task groups share one physical orchestration
        # admission Authority and the same resource identity. Its fixed policy
        # ceiling is an upper bound on outstanding graph nodes, never a permit:
        # we still acquire every permit from the owning group. Once the local
        # cut reaches the ceiling, no further Unit can be admitted until one
        # completes, so resampling/sorting the entire ready frontier at each
        # 50-ms heartbeat is provably redundant.
        admission = self._pool.orchestration_admission_snapshot()
        blocking_lane = next(
            lane for lane in admission.lanes
            if lane.lane_kind is ExecutionLaneKind.BLOCKING_IO
        )
        dispatch_ceiling = min(
            admission.max_total_in_flight,
            admission.max_in_flight_per_group,
            admission.max_in_flight_per_tenant,
            admission.max_in_flight_per_resource,
            blocking_lane.max_in_flight,
        )
        if dispatch_ceiling <= 0:
            raise ResearchGraphExecutionConflict(
                "research graph has no blocking orchestration admission capacity"
            )
        # This is the only ready/priority index. The Unit frontier owns
        # dependency truth and emits exactly-once transitions; Scheduling
        # Authority alone owns globally changing fair-order keys.
        dispatch_index = ResearchGraphDispatchIndex(
            self._pool.scheduling_authority,
            lambda node_id: self._scheduling_candidate(
                self._plan_index.by_id[node_id], deadline=deadline,
            ),
        )
        parked_control_probe_ns = 0
        running: dict[str, tuple[NoetriumUnit, object, int]] = {}
        renewal_interval_ns = max(1, self._lease_ns // 3)
        attempts = _DurableAttemptBook()
        # A typed claim-published event wakes the owner immediately when a
        # worker registers its lease. Without this, a worker can claim after
        # the owner checked an empty lease book and then expire while the
        # owner waits for a completion that cannot happen yet.
        completion_queue: Queue[tuple[str, str]] = Queue()
        submission_counts: dict[str, int] = {}

        def submission_pair(node: NoetriumUnit):
            node_id = execution_vertex_id(node)
            submission_number = submission_counts.get(node_id, 0) + 1

            def run(context, owned_node=node):
                try:
                    claim_now_ns = time.time_ns()
                    claim = store.claim(
                        execution_id,
                        execution_vertex_id(owned_node),
                        owner_id=self._scheduler_owner_id,
                        now_ns=claim_now_ns,
                        lease_expires_at_ns=claim_now_ns + self._lease_ns,
                    )
                    attempt_id = claim.attempt_id
                    if attempt_id is None:
                        raise RuntimeError(
                            "claimed research graph node lost attempt id"
                        )
                    attempts.publish(
                        execution_vertex_id(owned_node),
                        attempt_id,
                        claim_now_ns + renewal_interval_ns,
                        claim.lease_expires_at_ns or (claim_now_ns + self._lease_ns),
                    )
                    completion_queue.put(
                        ("claimed", execution_vertex_id(owned_node))
                    )
                    store.mark_running(
                        execution_id,
                        execution_vertex_id(owned_node),
                        attempt_id=attempt_id,
                        owner_id=self._scheduler_owner_id,
                        now_ns=time.time_ns(),
                    )
                    context.checkpoint()
                    self._executor.execute(
                        _AttemptTaskContext(context, attempt_id),
                        owned_node,
                        deadline=deadline,
                    )
                    context.checkpoint()
                finally:
                    completion_queue.put(
                        ("completed", execution_vertex_id(owned_node))
                    )

            return (
                ExecutionSpec(
                    task_id=(
                        f"research-graph-node:{execution_id}:{node_id}:"
                        f"submission:{submission_number}"
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
                submission_number,
            )

        def submit_blocking(node: NoetriumUnit):
            spec, run, submission_number = submission_pair(node)
            handle = fair_group.submit(
                spec,
                run,
                deadline=deadline,
            )
            submission_counts[execution_vertex_id(node)] = submission_number
            return handle

        def submit_maximal(nodes: tuple[NoetriumUnit, ...]):
            if not nodes:
                return ()
            rows = tuple(submission_pair(node) for node in nodes)
            handles = opportunistic_group.try_submit_maximal_batch(
                tuple((spec, run) for spec, run, _number in rows),
                deadline=deadline,
            )
            for index, (node, (_spec, _run, submission_number)) in enumerate(
                zip(nodes, rows, strict=True)
            ):
                if index >= len(handles):
                    break
                submission_counts[execution_vertex_id(node)] = submission_number
            return handles

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
            dispatch_index.forget(node_id)
            dispatch_index.invalidate_flow(
                execution_vertex_semantic_digest(
                    self._plan_index.by_id[node_id]
                ),
                now=time.monotonic(),
            )

        def materialize_missing(node_ids) -> None:
            missing = tuple(
                sorted(
                    node_id
                    for node_id in node_ids
                    if node_id not in live
                )
            )
            if not missing:
                return
            records = store.materialize_nodes(
                execution_id,
                self._plan,
                missing,
            )
            if {row.node_id for row in records} != set(missing):
                raise ResearchGraphExecutionConflict(
                    "sparse activation returned a different node set"
                )
            for record in records:
                live[record.node_id] = record

        lease_heartbeat_group = None
        lease_heartbeat = None

        def renew_graph_leases(context: TaskContextPort) -> None:
            context.checkpoint()
            self._renew_due_durable_leases(
                store=store,
                execution_id=execution_id,
                attempts=attempts,
                renewal_interval_ns=renewal_interval_ns,
                now_ns=time.time_ns(),
            )
            context.checkpoint()

        try:
            # Durable graph leases are liveness authority, not scheduler work.
            # Run their heartbeat in the isolated CRITICAL control domain so a
            # slow completion/materialization path cannot starve ownership.
            # The shared runtime heartbeat scheduler owns the only timer loop;
            # no polling thread or duplicate clock authority is introduced.
            lease_heartbeat_group = self._pool.open_control_group(
                f"{base_group_id}:durable-lease-heartbeat",
                tenant_id=self._tenant_id,
                resource_id=(
                    f"research-graph-lease:{execution_graph_id(self._plan)}"
                ),
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
            renewal_interval_seconds = renewal_interval_ns / 1_000_000_000
            lease_heartbeat = self._pool.control_heartbeats.register(
                lease_heartbeat_group.group_id,
                HeartbeatSpec(
                    heartbeat_id=(
                        f"{base_group_id}:durable-lease:{self._scheduler_owner_id}"
                    ),
                    lane_id=f"{base_group_id}:durable-lease-renewal",
                    interval_seconds=renewal_interval_seconds,
                    initial_delay_seconds=renewal_interval_seconds,
                    failure_scope=TaskFailureScope.GROUP,
                ),
                renew_graph_leases,
            )

            while pending or running:
                try:
                    lease_heartbeat.assert_healthy()
                except BaseException as renewal_failure:
                    reason = (
                        "research graph durable lease renewal lost owner authority"
                    )
                    opportunistic_group.cancel(reason)
                    fair_group.cancel(reason)
                    for _node_id, (
                        _node,
                        handle,
                        _started_ns,
                    ) in tuple(running.items()):
                        handle.cancel()
                    raise ResearchGraphExecutionConflict(reason) from renewal_failure
                current_control = control_store.control_state(execution_id)
                if current_control.phase in {
                    ResearchGraphControlPhase.PAUSED,
                    ResearchGraphControlPhase.RECOVERY_REQUIRED,
                    ResearchGraphControlPhase.CANCELLED,
                }:
                    reason = (
                        "durable research graph control halted live execution: "
                        + current_control.phase.value
                    )
                    # Future-style handle cancellation cannot preempt a running
                    # blocking worker. Cancel the owning structured task groups
                    # first so every in-flight TaskContext receives the same
                    # cooperative cancellation token at its next checkpoint.
                    # Durable graph control remains the authority; this is only
                    # its process-local enforcement path.
                    opportunistic_group.cancel(reason)
                    fair_group.cancel(reason)
                    for _node_id, (_node, handle, _started_ns) in tuple(running.items()):
                        handle.cancel()
                    raise ResearchGraphControlHalt(current_control)
                draining = (
                    current_control.phase is ResearchGraphControlPhase.DRAINING
                )

                if deadline is not None and deadline.expired:
                    reason = "durable research graph execution deadline expired"
                    opportunistic_group.cancel(reason)
                    fair_group.cancel(reason)
                    for _node_id, (_node, handle, _started_ns) in tuple(
                        running.items()
                    ):
                        handle.cancel()
                    raise TimeoutError(
                        "durable research graph execution deadline expired; "
                        "active leases will recover safely"
                    )

                progressed = False

                blocked_rows = frontier.drain_newly_blocked(pending.keys())
                if blocked_rows:
                    materialize_missing(
                        node_id for node_id, _blockers in blocked_rows
                    )
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
                            execution_vertex_id(node),
                            execution_vertex_semantic_digest(node),
                            ResearchGraphNodeState.BLOCKED,
                            blocked_by_node_ids=blockers,
                        )
                        results[node_id] = result
                        del pending[node_id]
                        frontier.record_terminal(result)
                        dispatch_index.forget(node_id)
                        progressed = True

                # Incremental ready transitions are the only way a newly
                # dependency-ready Unit enters the dispatch projection.
                # No full Ready enumeration, control-state materialization or
                # N-candidate sorting occurs on ordinary completion events.
                now_ns = time.time_ns()
                dispatch_index.offer_many(
                    frontier.drain_newly_ready(pending.keys()),
                    now=time.monotonic(),
                )
                retry_ready = dispatch_index.wake_due(now_ns=now_ns)
                if retry_ready:
                    dispatch_index.offer_many(
                        retry_ready, now=time.monotonic(),
                    )

                # Node-control changes made by a different process have no
                # in-process notification. Reconcile only parked controls at
                # a bounded interval; every actual dispatch also rechecks
                # authoritative per-node control before physical admission.
                if (
                    dispatch_index.parked_ids
                    and now_ns >= parked_control_probe_ns
                ):
                    parked_ids = dispatch_index.parked_ids
                    parked_rows = node_control_store.node_control_states(
                        execution_id, parked_ids,
                    )
                    if {row.node_id for row in parked_rows} != set(parked_ids):
                        raise ResearchGraphExecutionConflict(
                            "parked Unit control snapshot is incomplete"
                        )
                    reactivated = dispatch_index.release_parked(
                        row.node_id for row in parked_rows
                        if row.phase is ResearchGraphNodeControlPhase.ACTIVE
                        and (
                            live[row.node_id].state
                            is not ResearchGraphLiveNodeState.RETRY_WAIT
                            or live[row.node_id].retry_not_before_ns is None
                            or live[row.node_id].retry_not_before_ns <= now_ns
                        )
                    )
                    if reactivated:
                        dispatch_index.offer_many(
                            reactivated, now=time.monotonic(),
                        )
                    parked_control_probe_ns = (
                        now_ns + min(renewal_interval_ns, 500_000_000)
                    )

                if not draining and len(running) < dispatch_ceiling:
                    dispatch_slots = dispatch_ceiling - len(running)
                    cancelled_ids: list[str] = []
                    eligible_ids: list[str] = []
                    # Keep pulling small ranked batches until slots are filled
                    # or no indexed candidate remains. Paused/retry Units are
                    # parked rather than revisited on every scheduling tick.
                    while len(eligible_ids) < dispatch_slots:
                        ready_node_ids = dispatch_index.take(
                            dispatch_slots - len(eligible_ids),
                            now=time.monotonic(),
                        )
                        if not ready_node_ids:
                            break
                        materialize_missing(ready_node_ids)
                        control_rows = node_control_store.node_control_states(
                            execution_id, ready_node_ids,
                        )
                        node_controls = {
                            row.node_id: row for row in control_rows
                        }
                        if set(node_controls) != set(ready_node_ids):
                            raise ResearchGraphExecutionConflict(
                                "research graph node control batch lost ready nodes"
                            )

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
                                dispatch_index.park(
                                    node_id, retry_not_before_ns=None,
                                )
                                continue
                            if node_control.phase in {
                                ResearchGraphNodeControlPhase.PAUSED,
                                ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
                            }:
                                dispatch_index.park(
                                    node_id, retry_not_before_ns=None,
                                )
                                continue
                            current = live[node_id]
                            if (
                                current.state
                                is ResearchGraphLiveNodeState.RETRY_WAIT
                                and current.retry_not_before_ns is not None
                                and current.retry_not_before_ns > now_ns
                            ):
                                dispatch_index.park(
                                    node_id,
                                    retry_not_before_ns=current.retry_not_before_ns,
                                )
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
                                execution_vertex_id(node),
                                execution_vertex_semantic_digest(node),
                                ResearchGraphNodeState.CANCELLED,
                            )
                            del pending[node_id]
                            frontier.record_terminal(results[node_id])
                            dispatch_index.forget(node_id)
                            progressed = True

                    ordered_eligible_ids = tuple(eligible_ids)

                    if ordered_eligible_ids:
                        ready_records = store.mark_ready_many(
                            execution_id,
                            ordered_eligible_ids,
                            now_ns=now_ns,
                        )
                        ready_by_id = {
                            row.node_id: row for row in ready_records
                        }
                        if set(ready_by_id) != set(ordered_eligible_ids):
                            raise ResearchGraphExecutionConflict(
                                "ready batch returned a different node set"
                            )
                        for node_id in ordered_eligible_ids:
                            live[node_id] = ready_by_id[node_id]

                    remaining_ids = ordered_eligible_ids
                    if remaining_ids and not running:
                        first_id = remaining_ids[0]
                        node = pending[first_id]
                        try:
                            handle = submit_blocking(node)
                        except ExecutionPermitRejected as exc:
                            raise ResearchGraphExecutionConflict(
                                "fair research graph admission rejected a "
                                "single-node request"
                            ) from exc
                        frontier.consume_ready(first_id)
                        running[first_id] = (
                            node,
                            handle,
                            time.time_ns(),
                        )
                        del pending[first_id]
                        remaining_ids = remaining_ids[1:]
                        progressed = True

                    if remaining_ids:
                        remaining_nodes = tuple(
                            pending[node_id] for node_id in remaining_ids
                        )
                        handles = submit_maximal(remaining_nodes)
                        # The opportunistic capacity cut may accept only a
                        # prefix. Re-enqueue the untouched suffix immediately;
                        # its Frontier readiness and durable claim are intact.
                        if len(handles) < len(remaining_ids):
                            dispatch_index.offer_many(
                                remaining_ids[len(handles):],
                                now=time.monotonic(),
                            )
                        for node_id, node, handle in zip(
                            remaining_ids,
                            remaining_nodes,
                            handles,
                            strict=False,
                        ):
                            frontier.consume_ready(node_id)
                            running[node_id] = (
                                node,
                                handle,
                                time.time_ns(),
                            )
                            del pending[node_id]
                            progressed = True

                completed: list[str] = []
                while True:
                    try:
                        event_kind, event_node_id = completion_queue.get_nowait()
                    except Empty:
                        break
                    if event_kind == "completed" and event_node_id in running:
                        completed.append(event_node_id)
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
                    materialize_missing(pending.keys())
                    if self._handle_durable_stall(
                        execution_id=execution_id,
                        node_control_store=node_control_store,
                        pending=pending,
                        running=running,
                        reconciliation_required=reconciliation_required,
                        frontier=frontier,
                        dispatch_index=dispatch_index,
                        live=live,
                        completion_queue=completion_queue,
                        record_completion=record_completion,
                    ):
                        continue

                if not running:
                    continue

                # Actual work completion wakes immediately through the queue.
                # Only externally committed SQLite control/admission changes
                # require bounded polling. Durable lease renewal is isolated in
                # the control heartbeat authority; retries use their next known
                # absolute deadline instead of a fixed 50ms CPU wakeup loop.
                wait_seconds = 0.25
                retry_due_ns = dispatch_index.next_retry_ns()
                if retry_due_ns is not None:
                    wait_seconds = min(
                        wait_seconds,
                        max(0.0, (retry_due_ns-time.time_ns()) / 1_000_000_000),
                    )
                priority_transition = dispatch_index.next_rank_transition()
                if priority_transition is not None:
                    wait_seconds = min(
                        wait_seconds,
                        max(0.0, priority_transition - time.monotonic()),
                    )
                if deadline is not None:
                    wait_seconds = min(
                        wait_seconds, max(0.0, deadline.remaining_seconds),
                    )
                try:
                    event_kind, event_node_id = completion_queue.get(
                        timeout=wait_seconds
                    )
                except Empty:
                    continue
                if event_kind == "completed" and event_node_id in running:
                    record_completion(event_node_id)

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
                execution_graph_id(self._plan),
                execution_graph_digest(self._plan),
                execution_graph_research_revision_digest(self._plan),
                tuple(results[node_id] for node_id in sorted(results)),
            )
        finally:
            # On any unwind, cancel first and join the exact structured groups.
            # A graceful success path keeps cancel_pending false.  Once physical
            # worker convergence is proven, remaining locally-owned attempts can
            # be relinquished immediately instead of waiting for lease TTL.
            import sys

            close_errors: list[BaseException] = []
            worker_convergence_failed = False
            unwinding = sys.exc_info()[0] is not None
            cancel_pending = unwinding or (
                deadline.expired if deadline is not None else False
            )
            for owned_group in (opportunistic_group, fair_group):
                try:
                    self._pool.close_orchestration_group(
                        owned_group,
                        cancel_pending=cancel_pending,
                        deadline=deadline,
                    )
                except BaseException as exc:
                    close_errors.append(exc)
                    try:
                        if not owned_group.snapshot().converged:
                            worker_convergence_failed = True
                    except BaseException:
                        worker_convergence_failed = True

            if not worker_convergence_failed:
                recovery = (
                    store
                    if isinstance(store, ResearchGraphClaimRecoveryPort)
                    else None
                )
                if recovery is None and attempts.snapshot():
                    close_errors.append(
                        ResearchGraphExecutionConflict(
                            "research graph store cannot relinquish converged attempts"
                        )
                    )
                elif recovery is not None:
                    for node_id, attempt_id, _next_renewal_ns, _lease_expiry_ns in attempts.snapshot():
                        try:
                            current = store.node_state(execution_id, node_id)
                            if (
                                current.attempt_id != attempt_id
                                or current.lease_owner_id
                                != self._scheduler_owner_id
                            ):
                                attempts.drop(node_id)
                                continue
                            if current.state is ResearchGraphLiveNodeState.CLAIMED:
                                recovery.abandon_claim(
                                    execution_id,
                                    node_id,
                                    attempt_id=attempt_id,
                                    owner_id=self._scheduler_owner_id,
                                    now_ns=time.time_ns(),
                                )
                                attempts.drop(node_id)
                                continue
                            if current.state is ResearchGraphLiveNodeState.RUNNING:
                                recovery.relinquish_running_attempt(
                                    execution_id,
                                    node_id,
                                    attempt_id=attempt_id,
                                    owner_id=self._scheduler_owner_id,
                                    now_ns=time.time_ns(),
                                )
                                attempts.drop(node_id)
                                continue
                            attempts.drop(node_id)
                        except BaseException as exc:
                            close_errors.append(exc)

            # Keep lease renewal alive through worker convergence and durable
            # relinquish.  Only after no local attempt still needs ownership do
            # we retire the heartbeat's structured control lifetime.
            if lease_heartbeat is not None:
                try:
                    lease_heartbeat.cancel()
                except BaseException as exc:
                    close_errors.append(exc)
            if lease_heartbeat_group is not None:
                try:
                    # Cancellation is logical first; join the currently
                    # executing serial tick before unregistering admission.
                    # The bound is derived from the lease safety window rather
                    # than an unrelated fixed shutdown constant.
                    lease_heartbeat_group.wait(
                        timeout=(self._lease_ns + renewal_interval_ns)
                        / 1_000_000_000
                    )
                except BaseException as exc:
                    close_errors.append(exc)
                try:
                    self._pool.close_control_group(
                        lease_heartbeat_group,
                        cancel_pending=True,
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
