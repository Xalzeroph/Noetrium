from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.universal import UnitStepContext, UnitTransition

from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit

from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.research.experimentation.lifecycle.study.api.benchmark import (
    TaskRelation,
    task_graph,
    task_graph_relation,
    task_graph_relation_kind,
    task_graph_relation_source_id,
    task_graph_relation_target_id,
    validate_task_graph,
)

from noetrium_platform.research.experimentation.lifecycle.study.api import (
    assignment_workload,
    assignment_workload_dependencies_for,
    assignment_workload_digest,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    assignment_workload_task_ids,
    validate_assignment_workload,
    TaskRelation,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_task_unit,
    task_family,
    task_id as task_unit_id,
    task_lineage_id,
    task_max_seconds,
    task_max_steps,
)

from collections import deque
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from queue import Queue
from threading import Event, RLock
from time import monotonic
from dataclasses import dataclass, field, replace

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    Deadline,
    TaskDeadlineExceeded,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
    SingleFlightCache,
)
from noetrium_platform.foundation.kernel.kernel import (
    unit_execution_failure,
    ExecutionContext,
    MachineJournalPort,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.api import ScientificExecutionControlPort, UnitOperationBinding, unit_operation, executable_unit
from noetrium_platform.research.experimentation.lifecycle.experiment.api import (
    FailureScope,
)

from ..api import (
    WorkloadGraphResult,
    WorkloadTaskDeadlineExceeded,
    WorkloadTaskExecutionPort,
    WorkloadTaskResult,
    WorkloadTaskRunError,
    workload_task_result_from_payload,
    workload_task_result_payload,
)

_FRONTIER_OPERATION = "workload.frontier.execute"
_WORKLOAD_PROGRAM_VERSION = "3"


def _effective_limit(task_value, trial_value):
    if task_value is None:
        return trial_value
    if trial_value is None:
        return task_value
    return min(task_value, trial_value)


class _WorkloadExecutionBudgetControl(ScientificExecutionControlPort):
    """Scientific wall-clock control activated at actual child execution.

    Environment readiness is established by Trial preparation before workload
    execution. Platform unit-activation admission may still queue afterwards; that
    queue is infrastructure latency and must not consume the scientific task
    budget. The first admitted child worker activates one shared deadline.
    """

    __slots__ = (
        "_parent",
        "_worker",
        "_deadline",
        "_max_seconds",
        "_task_id",
        "_lock",
        "_active",
    )

    def __init__(
        self,
        parent: ExecutionControlPort,
        max_seconds: float | None,
        task_id: str,
        *,
        worker_control: ExecutionControlPort | None = None,
    ) -> None:
        if not isinstance(parent, ScientificExecutionControlPort):
            raise TypeError(
                "workload execution budget requires ScientificExecutionControlPort"
            )
        if worker_control is not None and not isinstance(worker_control, ExecutionControlPort):
            raise TypeError("workload worker control must satisfy ExecutionControlPort")
        self._parent = parent
        self._worker = worker_control
        self._task_id = str(task_id).strip()
        if not self._task_id:
            raise ValueError("workload execution budget requires task id")
        if max_seconds is None:
            self._max_seconds = None
        else:
            seconds = float(max_seconds)
            if seconds <= 0:
                raise ValueError("workload execution budget must be positive")
            self._max_seconds = seconds
        self._deadline: Deadline | None = None
        self._lock = RLock()
        self._active = False

    @property
    def scientific_time_active(self) -> bool:
        with self._lock:
            return self._active

    def activate_scientific_time(self) -> None:
        """Linearize the one scientific wall-clock start for this task."""
        self._parent.activate_scientific_time()
        if self._worker is not None:
            self._worker.checkpoint()
        self._parent.checkpoint()
        with self._lock:
            if self._active:
                return
            parent_scientific_deadline = self._parent.scientific_deadline
            if self._max_seconds is None:
                self._deadline = parent_scientific_deadline
            else:
                self._deadline = (
                    Deadline.after(self._max_seconds)
                    if parent_scientific_deadline is None
                    else parent_scientific_deadline.child(self._max_seconds)
                )
            self._active = True

    @property
    def cancelled(self) -> bool:
        return self._parent.cancelled or (
            self._worker is not None and self._worker.cancelled
        )

    @property
    def reason(self) -> str | None:
        if self._worker is not None and self._worker.cancelled:
            return self._worker.reason
        return self._parent.reason

    @property
    def scientific_deadline(self) -> Deadline | None:
        with self._lock:
            return (
                self._parent.scientific_deadline
                if not self._active else self._deadline
            )

    @property
    def deadline(self) -> Deadline | None:
        scientific = self.scientific_deadline
        worker = None if self._worker is None else self._worker.deadline
        if scientific is None:
            return worker
        if worker is None:
            return scientific
        return scientific if scientific.remaining_seconds <= worker.remaining_seconds else worker

    @property
    def scientific_deadline_expired(self) -> bool:
        deadline = self.scientific_deadline
        return bool(self.scientific_time_active and deadline is not None and deadline.expired)

    @property
    def remaining_seconds(self) -> float | None:
        deadline = self.deadline
        return None if deadline is None else deadline.remaining_seconds

    def subscribe_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        # A workload may be aborted by its Trial or its independently
        # admitted worker. Both are physical cancellation events; neither may
        # be replaced by periodic polling.
        parent_unsubscribe = self._parent.subscribe_cancel(callback)
        if self._worker is None:
            return parent_unsubscribe
        try:
            worker_unsubscribe = self._worker.subscribe_cancel(callback)
        except BaseException:
            parent_unsubscribe()
            raise

        def unsubscribe() -> None:
            worker_unsubscribe()
            parent_unsubscribe()

        return unsubscribe

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("workload execution control wait timeout cannot be negative")
        deadline = self.deadline
        bounded = timeout
        if deadline is not None:
            remaining = deadline.remaining_seconds
            bounded = remaining if timeout is None else min(float(timeout), remaining)
        signal = Event()
        unsubscribe = self.subscribe_cancel(signal.set)
        try:
            if self.cancelled or signal.wait(bounded) or self.cancelled:
                return True
            self.checkpoint()
            return False
        finally:
            unsubscribe()

    def checkpoint(self) -> None:
        if self._worker is not None:
            self._worker.checkpoint()
        self._parent.checkpoint()
        deadline = self.scientific_deadline
        if deadline is not None and deadline.expired:
            raise TaskDeadlineExceeded(
                "workload execution budget exceeded: " + self._task_id
            )


def _encode_task_result(value: WorkloadTaskResult) -> Mapping[str, object]:
    encoded = workload_task_result_payload(value)
    if not isinstance(encoded, Mapping):
        raise TypeError("workload task payload must encode to object")
    return encoded


def _decode_task_result(value: object) -> WorkloadTaskResult:
    return workload_task_result_from_payload(value)


def _compile_workload_program(workload: NoetriumUnit) -> NoetriumUnit:
    return executable_unit(
        f"workload:{assignment_workload_digest(workload)[:24]}",
        domain="run",
        version=_WORKLOAD_PROGRAM_VERSION,
        state_schema="noetrium.workload-unit-state.v4",
        entrypoint="frontier",
        members=(unit_operation(
            "frontier",
            _FRONTIER_OPERATION,
            configuration={
                "task_ids": assignment_workload_task_ids(workload),
                "workload_digest": assignment_workload_digest(workload),
                "dispatch": "completion-driven-ready-frontier",
            },
            max_visits=None,
        ),),
    )


@dataclass(slots=True)
class _WorkloadExecutionBinding:
    by_id: dict[str, NoetriumUnit]
    workload: NoetriumUnit
    context: ExecutionContext
    control: ExecutionControlPort
    ordinal_by_id: dict[str, int]
    task_group: TaskGroupPort | None
    completed_results: tuple[WorkloadTaskResult, ...] | None = None
    active: dict[str, object] = field(default_factory=dict)
    completion: Queue[str] = field(default_factory=Queue)


class WorkloadGraphBinding:
    """Execute an immutable workload DAG through one completion-driven frontier.

    Physical tasks remain durable deterministic child Machines. The parent
    Workload Machine owns scheduling/aggregation truth: replay reuses completed
    children while newly-ready dependents dispatch immediately after their own
    prerequisites finish, without fixed topological barriers.
    """

    def __init__(
        self,
        workload: WorkloadTaskExecutionPort,
        *,
        journal: MachineJournalPort,
        task_group: TaskGroupPort | None = None,
        task_group_scope=None,
    ) -> None:
        if not callable(getattr(workload, "execute_one", None)):
            raise TypeError("workload graph binding requires WorkloadTaskExecutionPort")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("workload graph binding requires durable MachineJournalPort")
        if task_group is not None and not callable(getattr(task_group, "submit", None)):
            raise TypeError("workload graph task_group must satisfy TaskGroupPort")
        if task_group_scope is not None and not callable(task_group_scope):
            raise TypeError("workload graph task_group_scope must be callable")
        if task_group is not None and task_group_scope is not None:
            raise ValueError("workload graph accepts one task-group authority")
        workload_identity = getattr(workload, "identity_digest", None)
        if type(workload_identity) is not str or len(workload_identity) != 64:
            raise TypeError("workload graph binding requires a task executor identity digest")
        self._workload = workload
        self._journal = journal
        self._task_group = task_group
        self._task_group_scope = task_group_scope
        self._program_cache: SingleFlightCache[NoetriumUnit] = SingleFlightCache()
        self._host_cache: SingleFlightCache[BoundExecutableUnit] = SingleFlightCache()
        self.identity_digest = canonical_digest({
            "binding": "workload-machine-program-binding.v4",
            "task_executor": workload_identity,
            "scheduling": "completion-driven-durable-frontier.v2",
        })

    def execute_one(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadTaskResult:
        return self._workload.execute_one(task, context, control)

    def _program_for(self, workload: NoetriumUnit) -> NoetriumUnit:
        digest = assignment_workload_digest(workload)
        return self._program_cache.get_or_create(
            digest,
            lambda: _compile_workload_program(workload),
        )

    @staticmethod
    def _child_context(
        context: ExecutionContext,
        task: NoetriumUnit,
        ordinal: int,
    ) -> ExecutionContext:
        task_budget = {}
        effective_steps = _effective_limit(
            task_max_steps(task),
            context.trial_budget.get("max_steps"),
        )
        effective_seconds = _effective_limit(
            task_max_seconds(task),
            context.trial_budget.get("max_seconds"),
        )
        if effective_steps is not None:
            task_budget["max_steps"] = int(effective_steps)
        if effective_seconds is not None:
            task_budget["max_seconds"] = float(effective_seconds)
        return replace(
            context,
            span_id=f"{context.span_id}:task:{ordinal:04d}",
            parent_span_id=context.span_id,
            task_id=task_unit_id(task),
            task_budget=task_budget,
            operation_id=f"{context.operation_id or context.span_id}:task:{ordinal:04d}",
            component_id="workload-program",
        )

    @staticmethod
    def _blocked_result(
        task: NoetriumUnit,
        failed_dependencies: tuple[str, ...],
    ) -> WorkloadTaskResult:
        return WorkloadTaskResult(
            task_id=task_unit_id(task),
            family=task_family(task),
            complete=False,
            success=False,
            utility=0.0,
            steps=0,
            duration_s=0.0,
            lineage_id=task_lineage_id(task),
            failure_reason=(
                "blocked by failed workload dependencies: "
                + ", ".join(failed_dependencies)
            ),
            blocked=True,
            failure_scope=FailureScope.TASK.value,
            diagnostics={
                "failed_dependencies": failed_dependencies,
                "blocked_by_workload_program": True,
            },
        )

    def _execute_frontier(
        self,
        request: UnitStepContext,
        binding: object,
    ) -> UnitTransition:
        if not isinstance(binding, _WorkloadExecutionBinding):
            raise TypeError(
                "workload frontier requires _WorkloadExecutionBinding"
            )
        execute = self._frontier_handler(
            by_id=binding.by_id,
            workload=binding.workload,
            context=binding.context,
            control=binding.control,
            ordinal_by_id=binding.ordinal_by_id,
            task_group=binding.task_group,
        )
        return execute(request, binding)

    def _host_for(self, workload: NoetriumUnit) -> BoundExecutableUnit:
        digest = assignment_workload_digest(workload)

        def build() -> BoundExecutableUnit:
            program = self._program_for(workload)
            operation = UnitOperationBinding(
                _FRONTIER_OPERATION,
                self._execute_frontier,
                canonical_digest({
                    "operation": _FRONTIER_OPERATION,
                    "binding_identity": self.identity_digest,
                    "workload_digest": digest,
                }),
            )
            return BoundExecutableUnit(
                host_id=f"workload:{digest[:24]}",
                unit=program,
                operations=(operation,),
                journal=self._journal,
                max_steps=None,
                dependency_identity={
                    "binding_identity": self.identity_digest,
                    "workload_digest": digest,
                },
            )

        return self._host_cache.get_or_create(digest, build)

    def _frontier_handler(
        self,
        *,
        by_id: dict[str, NoetriumUnit],
        workload: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
        ordinal_by_id: dict[str, int],
        task_group: TaskGroupPort | None,
    ):
        dependency_lists: dict[str, set[str]] = {
            task_id: set() for task_id in assignment_workload_task_ids(workload)
        }
        dependency_relations = {
            TaskRelation.PREREQUISITE,
            TaskRelation.RETRY_OF,
            TaskRelation.SEQUENCE_AFTER,
        }
        success_required_lists: dict[str, set[str]] = {
            task_id: set() for task_id in dependency_lists
        }
        for edge in workload.relations:
            if task_graph_relation_kind(edge) not in dependency_relations:
                continue
            target_id = task_graph_relation_target_id(edge)
            source_id = task_graph_relation_source_id(edge)
            dependency_lists[target_id].add(source_id)
            if task_graph_relation_kind(edge) is not TaskRelation.SEQUENCE_AFTER:
                success_required_lists[target_id].add(source_id)
        dependencies = {
            task_id: tuple(sorted(rows, key=ordinal_by_id.__getitem__))
            for task_id, rows in dependency_lists.items()
        }
        dependent_lists: dict[str, list[str]] = {
            task_id: [] for task_id in assignment_workload_task_ids(workload)
        }
        for task_id, dependency_ids in dependencies.items():
            for dependency_id in dependency_ids:
                dependent_lists[dependency_id].append(task_id)
        dependents = {
            task_id: tuple(sorted(rows, key=ordinal_by_id.__getitem__))
            for task_id, rows in dependent_lists.items()
        }

        def execute(request: UnitStepContext, _binding: object) -> UnitTransition:
            if not isinstance(_binding, _WorkloadExecutionBinding):
                raise TypeError(
                    "workload frontier requires _WorkloadExecutionBinding"
                )

            semantic = thaw_json(request.semantic_state)
            result_prefix = "workload-result:"
            results: dict[str, WorkloadTaskResult] = {}
            for key, value in semantic.items():
                if not isinstance(key, str) or not key.startswith(result_prefix):
                    continue
                task_id = key[len(result_prefix):]
                if task_id not in by_id:
                    raise ValueError(
                        "workload durable result references unknown task"
                    )
                if task_id in results:
                    raise ValueError(
                        "workload durable result task identity duplicated"
                    )
                result = _decode_task_result(value)
                if result.task_id != task_id:
                    raise ValueError(
                        "workload durable result task identity drift"
                    )
                results[task_id] = result

            active = _binding.active
            completion = _binding.completion
            all_task_ids = assignment_workload_task_ids(workload)

            def accept_result(
                task_id: str,
                result: WorkloadTaskResult,
                durable: dict[str, Mapping[str, object]],
            ) -> None:
                task = by_id[task_id]
                if result.task_id != task_unit_id(task):
                    raise ValueError(
                        "workload Program result task identity drift"
                    )
                scope = FailureScope(result.failure_scope)
                if not result.success and scope is not FailureScope.TASK:
                    raise WorkloadTaskRunError(
                        "graph",
                        "wider-scope-task-failure",
                        f"task {task_unit_id(task)!r} failed with scope={scope.value}",
                        scope=scope,
                    )
                results[task_id] = result
                durable[result_prefix + task_id] = _encode_task_result(result)

            def settle_blocked(
                durable: dict[str, Mapping[str, object]],
            ) -> None:
                changed = True
                while changed:
                    changed = False
                    for task_id in all_task_ids:
                        if task_id in results or task_id in active:
                            continue
                        dependency_ids = dependencies[task_id]
                        if any(dep not in results for dep in dependency_ids):
                            continue
                        failed = tuple(
                            dep
                            for dep in success_required_lists[task_id]
                            if not results[dep].success
                        )
                        if not failed:
                            continue
                        accept_result(
                            task_id,
                            self._blocked_result(by_id[task_id], failed),
                            durable,
                        )
                        changed = True

            def run_one(
                task_id: str,
                scientific_control: ExecutionControlPort,
                *,
                worker_control: ExecutionControlPort | None = None,
            ) -> WorkloadTaskResult:
                task = by_id[task_id]
                execution_control = _WorkloadExecutionBudgetControl(
                    scientific_control,
                    _effective_limit(
                        task_max_seconds(task),
                        context.trial_budget.get("max_seconds"),
                    ),
                    task_unit_id(task),
                    worker_control=worker_control,
                )
                started = monotonic()
                def scientific_timeout_result(
                    exc: TaskDeadlineExceeded,
                    *,
                    trigger: BaseException | None = None,
                ) -> WorkloadTaskResult:
                    # Only the scientific clock may censor a research outcome.
                    # Worker/parent infrastructure deadlines remain fatal to the
                    # execution attempt and must never be relabelled as task data.
                    if (
                        not execution_control.scientific_deadline_expired
                        or scientific_control.cancelled
                        or (worker_control is not None and worker_control.cancelled)
                    ):
                        raise exc
                    partial = (
                        exc.partial_measurement
                        if isinstance(exc, WorkloadTaskDeadlineExceeded)
                        else None
                    )
                    partial_diagnostics = (
                        {} if partial is None else dict(partial.diagnostics)
                    )
                    trigger_diagnostics = {} if trigger is None else {
                        "deadline_detection_source": (
                            "execution_control_checkpoint_after_timeout"
                        ),
                        "deadline_trigger_type": type(trigger).__name__,
                    }
                    return WorkloadTaskResult(
                        task_id=task_unit_id(task),
                        family=task_family(task),
                        complete=False,
                        success=False,
                        utility=0.0,
                        steps=0 if partial is None else partial.steps,
                        duration_s=max(0.0, monotonic() - started),
                        lineage_id=task_lineage_id(task),
                        failure_reason=str(exc),
                        failure_scope=FailureScope.TASK.value,
                        diagnostics={
                            **partial_diagnostics,
                            **trigger_diagnostics,
                            "scientific_censored": True,
                            "step_count_unobserved": partial is None,
                            "partial_measurement_observed": partial is not None,
                            "cause_type": "TaskDeadlineExceeded",
                            "duration_semantics": "task_execution_attempt",
                        },
                    )

                try:
                    return self._workload.execute_one(
                        task,
                        self._child_context(
                            context,
                            task,
                            ordinal_by_id[task_id],
                        ),
                        execution_control,
                    )
                except TaskDeadlineExceeded as exc:
                    return scientific_timeout_result(exc)
                except TimeoutError as exc:
                    # Admission/providers may observe the shared deadline before
                    # the workload boundary gets another checkpoint. Re-read the
                    # authoritative scientific clock: convert only if that clock
                    # itself has expired; otherwise preserve the infrastructure
                    # timeout exactly.
                    if not execution_control.scientific_deadline_expired:
                        raise
                    deadline_exc = TaskDeadlineExceeded(
                        "workload execution budget exceeded: " + task_unit_id(task)
                    )
                    return scientific_timeout_result(deadline_exc, trigger=exc)

            def ready_ids() -> deque[str]:
                ready = deque()
                for task_id in all_task_ids:
                    if task_id in results or task_id in active:
                        continue
                    dependency_ids = dependencies[task_id]
                    if any(dep not in results for dep in dependency_ids):
                        continue
                    if any(
                        not results[dep].success
                        for dep in success_required_lists[task_id]
                    ):
                        continue
                    ready.append(task_id)
                return ready

            def task_pair(task_id: str):
                if task_group is None:
                    raise RuntimeError(
                        "workload concurrent submit requires TaskGroupPort"
                    )
                task = by_id[task_id]

                def run(task_context, owned_id=task_id):
                    try:
                        return run_one(
                            owned_id,
                            control,
                            worker_control=task_context,
                        )
                    finally:
                        completion.put(owned_id)

                return (
                    ExecutionSpec(
                        task_id=(
                            f"workload:{context.lifetime_id or context.run_id}:"
                            f"{task_unit_id(task)}"
                        ),
                        lane_kind=ExecutionLaneKind.BLOCKING_IO,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    run,
                )

            def submit_blocking(task_id: str) -> None:
                if task_group is None:
                    raise RuntimeError(
                        "workload concurrent submit requires TaskGroupPort"
                    )
                spec, run = task_pair(task_id)
                active[task_id] = task_group.submit(
                    spec,
                    run,
                    deadline=control.deadline,
                )

            def abort_active(primary: BaseException) -> None:
                remaining = tuple(active.values())
                convergence_errors: list[BaseException] = []
                for handle in remaining:
                    try:
                        handle.cancel()
                    except BaseException as exc:
                        convergence_errors.append(exc)
                for handle in remaining:
                    try:
                        handle.result()
                    except BaseException:
                        pass
                active.clear()
                if convergence_errors:
                    raise ExceptionGroup(
                        "workload frontier abort convergence failed",
                        [primary, *convergence_errors],
                    ) from primary
                raise primary

            durable: dict[str, Mapping[str, object]] = {}
            settle_blocked(durable)

            if len(results) == len(all_task_ids):
                ordered = tuple(results[task_id] for task_id in all_task_ids)
                _binding.completed_results = ordered
                return UnitTransition.goto(
                    value={"completed_task_ids": all_task_ids},
                    semantic_delta=durable,
                    events=(
                        {
                            "type": "workload_completed",
                            "completed_task_count": len(ordered),
                        },
                    ),
                    progress=True,
                )

            if task_group is None:
                ready = ready_ids()
                if not ready:
                    raise RuntimeError(
                        "validated workload DAG stalled without a ready task"
                    )
                completed_id = ready.popleft()
                try:
                    accept_result(
                        completed_id,
                        run_one(completed_id, control),
                        durable,
                    )
                except BaseException as exc:
                    abort_active(exc)
            else:
                ready = ready_ids()
                if ready:
                    # The ready frontier is already one coherent policy input.
                    # Let Admission choose its exact maximal current prefix in
                    # one batch before manufacturing a single-task blocking
                    # grant. This keeps the common idle+capacity path to one
                    # scheduling/durability cut. If no immediate permit exists,
                    # the historical blocking-one fallback still guarantees
                    # progress without polling or a batching delay.
                    ready_tuple = tuple(ready)
                    pairs = tuple(task_pair(task_id) for task_id in ready_tuple)
                    handles = task_group.try_submit_maximal_batch(
                        pairs,
                        deadline=control.deadline,
                    )
                    for task_id, handle in zip(
                        ready_tuple,
                        handles,
                        strict=False,
                    ):
                        active[task_id] = handle
                    if not active:
                        submit_blocking(ready_tuple[0])

                if not active:
                    settle_blocked(durable)
                    if len(results) == len(all_task_ids):
                        ordered = tuple(
                            results[task_id] for task_id in all_task_ids
                        )
                        _binding.completed_results = ordered
                        return UnitTransition.goto(
                            value={"completed_task_ids": all_task_ids},
                            semantic_delta=durable,
                            events=(
                                {
                                    "type": "workload_completed",
                                    "completed_task_count": len(ordered),
                                },
                            ),
                            progress=True,
                        )
                    raise RuntimeError(
                        "validated workload DAG stalled without active or ready tasks"
                    )

                completed_id = completion.get()
                handle = active.pop(completed_id)
                try:
                    value = handle.result()
                    if not isinstance(value, WorkloadTaskResult):
                        raise TypeError(
                            "workload task executor returned invalid result"
                        )
                    accept_result(completed_id, value, durable)
                except BaseException as exc:
                    abort_active(exc)

            settle_blocked(durable)
            completed = len(results) == len(all_task_ids)
            if completed:
                ordered = tuple(results[task_id] for task_id in all_task_ids)
                _binding.completed_results = ordered

            return UnitTransition.goto(
                None if completed else "frontier",
                value={
                    "completed_task_ids": tuple(
                        task_id
                        for task_id in all_task_ids
                        if task_id in results
                    ),
                    "latest_completed_task_id": completed_id,
                },
                semantic_delta=durable,
                events=(
                    {
                        "type": "workload_task_completed",
                        "task_id": completed_id,
                        "completed_task_count": len(results),
                        "remaining_task_count": len(all_task_ids) - len(results),
                    },
                ),
                progress=True,
            )
        return execute

    def execute_graph(
        self,
        tasks: tuple[NoetriumUnit, ...],
        workload: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadGraphResult:
        if type(tasks) is not tuple or not tasks:
            raise TypeError("workload graph execution requires a non-empty task tuple")
        for task in tasks:
            require_task_unit(task)
        validate_assignment_workload(workload)
        if not isinstance(context, ExecutionContext):
            raise TypeError("workload graph execution requires ExecutionContext")
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("workload graph execution requires ExecutionControlPort")
        control.checkpoint()
        by_id = {task_unit_id(task): task for task in tasks}
        if len(by_id) != len(tasks):
            raise ValueError("workload graph task ids must be unique")
        if set(by_id) != set(assignment_workload_task_ids(workload)):
            raise ValueError(
                "workload graph task projection does not match assignment workload"
            )

        ordinal_by_id = {
            task_id: index for index, task_id in enumerate(assignment_workload_task_ids(workload))
        }
        program = self._program_for(workload)
        group_scope = (
            self._task_group_scope(context)
            if self._task_group_scope is not None
            else nullcontext(self._task_group)
        )
        with group_scope as task_group:
            if task_group is not None and not callable(
                getattr(task_group, "submit", None)
            ):
                raise TypeError(
                    "workload task-group scope returned invalid TaskGroupPort"
                )
            binding = _WorkloadExecutionBinding(
                by_id=by_id,
                workload=workload,
                context=context,
                control=control,
                ordinal_by_id=ordinal_by_id,
                task_group=task_group,
            )
            host = self._host_for(workload)
            machine_id = (
                "workload:"
                + canonical_digest({
                    "run_id": context.run_id,
                    "study_id": context.study_id,
                    "condition_id": context.condition_id,
                    "lifetime_id": context.lifetime_id,
                    "branch_id": context.branch_id,
                    "workload_digest": assignment_workload_digest(workload),
                })[:40]
            )
            execution = host.execute(
                machine_id=machine_id,
                instance_identity={
                    "workload_digest": assignment_workload_digest(workload),
                    "task_ids": assignment_workload_task_ids(workload),
                    "run_id": context.run_id,
                    "lifetime_id": context.lifetime_id,
                },
                binding=binding,
                initial_data={},
                command_id_prefix=machine_id,
            )

        if execution.status is MachineStatus.FAILED:
            failure = unit_execution_failure(
                execution.semantic_state,
                surface="workload NoetriumUnit",
            )
            raise WorkloadTaskRunError(
                "graph",
                "workload-program-failed",
                str(failure),
                scope=FailureScope.RUN,
            ) from failure
        if execution.status is not MachineStatus.COMPLETED:
            raise WorkloadTaskRunError(
                "graph",
                "workload-program-incomplete",
                f"workload NoetriumUnit stopped with {execution.status.value}",
                scope=FailureScope.RUN,
            )
        if binding.completed_results is not None:
            return WorkloadGraphResult(binding.completed_results)
        semantic = thaw_json(execution.semantic_state)
        result_prefix = "workload-result:"
        results = {}
        for task_id in assignment_workload_task_ids(workload):
            key = result_prefix + task_id
            if key not in semantic:
                raise RuntimeError(
                    "completed workload Program has no durable result for task "
                    + task_id
                )
            results[task_id] = _decode_task_result(semantic[key])
        return WorkloadGraphResult(
            tuple(results[task_id] for task_id in assignment_workload_task_ids(workload))
        )


__all__ = ["WorkloadGraphBinding"]
