from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from queue import Queue
from dataclasses import replace
from threading import Lock

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    MachineJournalPort,
    MachineKind,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.api import (
    ProgramNode,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    ExperimentTaskSpec,
    FailureScope,
    TaskGraphRelation,
)

from ..api import (
    WorkloadGraphResult,
    WorkloadTaskExecutionPort,
    WorkloadTaskResult,
    WorkloadTaskRunError,
    workload_task_result_from_payload,
    workload_task_result_payload,
)

_FRONTIER_OPERATION = "workload.frontier.execute"
_WORKLOAD_PROGRAM_VERSION = "2"


def _encode_task_result(value: WorkloadTaskResult) -> dict[str, object]:
    encoded = thaw_json(workload_task_result_payload(value))
    if not isinstance(encoded, dict):
        raise TypeError("workload task payload must decode to object")
    return encoded


def _decode_task_result(value: object) -> WorkloadTaskResult:
    return workload_task_result_from_payload(value)


def _topological_waves(workload: AssignmentWorkload) -> tuple[tuple[str, ...], ...]:
    """Compile a validated immutable DAG into deterministic ready-set waves.

    This is compilation, not execution state: no runtime cursor, retry state or
    task completion truth lives here. Runtime progress belongs only to the
    ResearchProgram Machine Journal.

    The immutable workload has already been validated as a DAG. Build one
    dependency index and advance Kahn frontiers instead of rescanning every task
    and every edge for every wave. Canonical task order remains the tie-breaker.
    """
    order_index = {
        task_id: index
        for index, task_id in enumerate(workload.task_ids)
    }
    indegree = {task_id: 0 for task_id in workload.task_ids}
    dependents: dict[str, set[str]] = {
        task_id: set()
        for task_id in workload.task_ids
    }
    dependency_relations = {
        TaskGraphRelation.PREREQUISITE,
        TaskGraphRelation.RETRY_OF,
    }
    for edge in workload.task_graph.edges:
        if edge.relation not in dependency_relations:
            continue
        targets = dependents[edge.source_task_id]
        if edge.target_task_id in targets:
            continue
        targets.add(edge.target_task_id)
        indegree[edge.target_task_id] += 1

    ready = tuple(
        task_id
        for task_id in workload.task_ids
        if indegree[task_id] == 0
    )
    waves: list[tuple[str, ...]] = []
    emitted_count = 0
    while ready:
        waves.append(ready)
        emitted_count += len(ready)
        next_ready: list[str] = []
        for task_id in ready:
            for target_id in dependents[task_id]:
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    next_ready.append(target_id)
        next_ready.sort(key=order_index.__getitem__)
        ready = tuple(next_ready)

    if emitted_count != len(workload.task_ids):
        raise RuntimeError(
            "validated workload DAG produced an incomplete topological frontier"
        )
    return tuple(waves)


def _compile_workload_program(workload: AssignmentWorkload) -> ResearchProgram:
    node = ProgramNode(
        node_id="frontier",
        operation=_FRONTIER_OPERATION,
        configuration={
            "task_ids": workload.task_ids,
            "workload_digest": workload.workload_digest,
            "dispatch": "completion-driven-ready-frontier",
        },
        next_node=None,
        allowed_next_nodes=(),
        max_visits=1,
    )
    return ResearchProgram(
        program_id=f"workload:{workload.workload_digest[:24]}",
        kind=MachineKind.RUN,
        version=_WORKLOAD_PROGRAM_VERSION,
        state_schema="noetrium.workload-program-state.v2",
        entrypoint=node.node_id,
        nodes=(node,),
    )


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
        self._program_cache_lock = Lock()
        self._program_cache: dict[str, ResearchProgram] = {}
        self.identity_digest = canonical_digest({
            "binding": "workload-research-program-binding.v4",
            "task_executor": workload_identity,
            "scheduling": "completion-driven-ready-frontier.v1",
        })

    def execute_one(
        self,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
    ) -> WorkloadTaskResult:
        return self._workload.execute_one(task, context)

    def _program_for(self, workload: AssignmentWorkload) -> ResearchProgram:
        digest = workload.workload_digest
        with self._program_cache_lock:
            cached = self._program_cache.get(digest)
            if cached is not None:
                return cached
        compiled = _compile_workload_program(workload)
        with self._program_cache_lock:
            current = self._program_cache.get(digest)
            if current is not None:
                if current.program_digest != compiled.program_digest:
                    raise RuntimeError(
                        "workload program identity drifted for immutable workload"
                    )
                return current
            self._program_cache[digest] = compiled
            return compiled

    @staticmethod
    def _child_context(
        context: ExecutionContext,
        task: ExperimentTaskSpec,
        ordinal: int,
    ) -> ExecutionContext:
        return replace(
            context,
            span_id=f"{context.span_id}:task:{ordinal:04d}",
            parent_span_id=context.span_id,
            task_id=task.task_id,
            operation_id=f"{context.operation_id or context.span_id}:task:{ordinal:04d}",
            component_id="workload-program",
        )

    @staticmethod
    def _blocked_result(
        task: ExperimentTaskSpec,
        failed_dependencies: tuple[str, ...],
    ) -> WorkloadTaskResult:
        return WorkloadTaskResult(
            task_id=task.task_id,
            family=task.family,
            success=False,
            utility=0.0,
            steps=0,
            duration_s=0.0,
            lineage_id=task.lineage_id,
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

    def _frontier_handler(
        self,
        *,
        by_id: dict[str, ExperimentTaskSpec],
        workload: AssignmentWorkload,
        context: ExecutionContext,
        ordinal_by_id: dict[str, int],
        task_group: TaskGroupPort | None,
    ):
        dependency_lists: dict[str, list[str]] = {
            task_id: [] for task_id in workload.task_ids
        }
        dependency_relations = {
            TaskGraphRelation.PREREQUISITE,
            TaskGraphRelation.RETRY_OF,
        }
        for edge in workload.task_graph.edges:
            if edge.relation not in dependency_relations:
                continue
            rows = dependency_lists[edge.target_task_id]
            if edge.source_task_id not in rows:
                rows.append(edge.source_task_id)
        dependencies = {
            task_id: tuple(sorted(rows, key=ordinal_by_id.__getitem__))
            for task_id, rows in dependency_lists.items()
        }

        def execute(request: ProgramNodeRequest, _binding: object) -> ProgramNodeResult:
            semantic = thaw_json(request.semantic_state)
            raw_results = semantic.get("workload_results", {})
            if not isinstance(raw_results, dict):
                raise TypeError("workload Program result state must be an object")
            results: dict[str, WorkloadTaskResult] = {
                task_id: _decode_task_result(value)
                for task_id, value in raw_results.items()
            }
            unresolved = {
                task_id for task_id in workload.task_ids if task_id not in results
            }
            active: dict[str, object] = {}
            completion: Queue[str] = Queue()
            errors: list[BaseException] = []
            draining = False

            def accept_result(task_id: str, result: WorkloadTaskResult) -> None:
                task = by_id[task_id]
                if result.task_id != task.task_id:
                    raise ValueError("workload Program result task identity drift")
                scope = FailureScope(result.failure_scope)
                if not result.success and scope is not FailureScope.TASK:
                    raise WorkloadTaskRunError(
                        "graph",
                        "wider-scope-task-failure",
                        f"task {task.task_id!r} failed with scope={scope.value}",
                        scope=scope,
                    )
                results[task_id] = result

            def settle_blocked() -> None:
                while True:
                    blocked_now: list[tuple[str, tuple[str, ...]]] = []
                    for task_id in workload.task_ids:
                        if task_id not in unresolved:
                            continue
                        deps = dependencies[task_id]
                        if not deps or any(dep not in results for dep in deps):
                            continue
                        failed = tuple(
                            dep for dep in deps if not results[dep].success
                        )
                        if failed:
                            blocked_now.append((task_id, failed))
                    if not blocked_now:
                        return
                    for task_id, failed in blocked_now:
                        results[task_id] = self._blocked_result(
                            by_id[task_id],
                            failed,
                        )
                        unresolved.remove(task_id)

            def ready_ids() -> tuple[str, ...]:
                return tuple(
                    task_id
                    for task_id in workload.task_ids
                    if task_id in unresolved
                    and all(dep in results for dep in dependencies[task_id])
                    and all(
                        results[dep].success for dep in dependencies[task_id]
                    )
                )

            def run_one(task_id: str) -> WorkloadTaskResult:
                task = by_id[task_id]
                return self._workload.execute_one(
                    task,
                    self._child_context(
                        context,
                        task,
                        ordinal_by_id[task_id],
                    ),
                )

            def submit(task_id: str) -> None:
                task = by_id[task_id]

                def run(_task_context, owned_id=task_id):
                    try:
                        return run_one(owned_id)
                    finally:
                        completion.put(owned_id)

                active[task_id] = task_group.submit(
                    ExecutionSpec(
                        task_id=(
                            f"workload:{context.lifetime_id or context.run_id}:"
                            f"{task.task_id}"
                        ),
                        lane_kind=ExecutionLaneKind.BLOCKING_IO,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    run,
                    deadline=Deadline.after(float(task.max_seconds)),
                )
                unresolved.remove(task_id)

            if task_group is None:
                while unresolved:
                    settle_blocked()
                    ready = ready_ids()
                    if not ready:
                        if unresolved:
                            raise RuntimeError(
                                "validated workload DAG stalled without a ready task"
                            )
                        break
                    for task_id in ready:
                        unresolved.remove(task_id)
                        accept_result(task_id, run_one(task_id))
            else:
                while unresolved or active:
                    if not draining:
                        settle_blocked()
                        for task_id in ready_ids():
                            submit(task_id)
                    if not active:
                        if draining and errors:
                            break
                        if unresolved:
                            raise RuntimeError(
                                "validated workload DAG stalled without active or ready tasks"
                            )
                        break
                    completed_id = completion.get()
                    handle = active.pop(completed_id)
                    try:
                        value = handle.result()
                        if not isinstance(value, WorkloadTaskResult):
                            raise TypeError(
                                "workload task executor returned invalid result"
                            )
                        accept_result(completed_id, value)
                    except BaseException as exc:
                        errors.append(exc)
                        draining = True
                if errors:
                    raise ExceptionGroup(
                        "workload completion-driven dispatch failed",
                        errors,
                    )

            encoded = {
                task_id: _encode_task_result(results[task_id])
                for task_id in workload.task_ids
            }
            return ProgramNodeResult(
                value={"completed_task_ids": tuple(encoded)},
                semantic_state_update={"workload_results": encoded},
            )
        return execute

    def execute_graph(
        self,
        tasks: tuple[ExperimentTaskSpec, ...],
        workload: AssignmentWorkload,
        context: ExecutionContext,
    ) -> WorkloadGraphResult:
        if type(tasks) is not tuple or not tasks:
            raise TypeError("workload graph execution requires a non-empty task tuple")
        if any(not isinstance(task, ExperimentTaskSpec) for task in tasks):
            raise TypeError("workload graph execution tasks must be ExperimentTaskSpec")
        if type(workload) is not AssignmentWorkload:
            raise TypeError("workload graph execution requires AssignmentWorkload")
        if not isinstance(context, ExecutionContext):
            raise TypeError("workload graph execution requires ExecutionContext")
        by_id = {task.task_id: task for task in tasks}
        if len(by_id) != len(tasks):
            raise ValueError("workload graph task ids must be unique")
        if set(by_id) != set(workload.task_ids):
            raise ValueError(
                "workload graph task projection does not match assignment workload"
            )

        ordinal_by_id = {
            task_id: index for index, task_id in enumerate(workload.task_ids)
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
            operation = ResearchHostOperation(
                _FRONTIER_OPERATION,
                self._frontier_handler(
                    by_id=by_id,
                    workload=workload,
                    context=context,
                    ordinal_by_id=ordinal_by_id,
                    task_group=task_group,
                ),
                canonical_digest({
                    "operation": _FRONTIER_OPERATION,
                    "binding_identity": self.identity_digest,
                    "workload_digest": workload.workload_digest,
                }),
            )
            host = ResearchProgramHost(
                host_id=f"workload:{workload.workload_digest[:24]}",
                program=program,
                operations=(operation,),
                journal=self._journal,
                max_steps=2,
                dependency_identity={
                    "binding_identity": self.identity_digest,
                    "workload_digest": workload.workload_digest,
                },
            )
            machine_id = (
                "workload:"
                + canonical_digest({
                    "run_id": context.run_id,
                    "study_id": context.study_id,
                    "condition_id": context.condition_id,
                    "lifetime_id": context.lifetime_id,
                    "branch_id": context.branch_id,
                    "workload_digest": workload.workload_digest,
                })[:40]
            )
            execution = host.execute(
                machine_id=machine_id,
                instance_identity={
                    "workload_digest": workload.workload_digest,
                    "task_ids": workload.task_ids,
                    "run_id": context.run_id,
                    "lifetime_id": context.lifetime_id,
                },
                binding=self,
                initial_data={},
                command_id_prefix=machine_id,
            )

        if execution.status is not MachineStatus.COMPLETED:
            failure = thaw_json(execution.semantic_state).get("program_failure")
            raise WorkloadTaskRunError(
                "graph",
                "workload-program-failed",
                (
                    "workload ResearchProgram stopped with "
                    f"{execution.status.value}: {failure!r}"
                ),
                scope=FailureScope.RUN,
            )
        semantic = thaw_json(execution.semantic_state)
        raw_results = semantic.get("workload_results")
        if not isinstance(raw_results, dict):
            raise RuntimeError("completed workload Program has no result state")
        results = {
            task_id: _decode_task_result(raw_results[task_id])
            for task_id in workload.task_ids
        }
        return WorkloadGraphResult(
            tuple(results[task_id] for task_id in workload.task_ids)
        )


__all__ = ["WorkloadGraphBinding"]
