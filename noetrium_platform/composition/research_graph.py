from __future__ import annotations

import time
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
    ResearchGraphExecutionReport,
    ResearchGraphNode,
    ResearchGraphNodeExecutorPort,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    ResearchGraphPlan,
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
        execution_pool: ResearchExecutionPool | None = None,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        task_group_id: str | None = None,
    ) -> None:
        if type(plan) is not ResearchGraphPlan:
            raise TypeError("research graph scheduler requires ResearchGraphPlan")
        if not isinstance(executor, ResearchGraphNodeExecutorPort):
            raise TypeError(
                "research graph scheduler executor must satisfy ResearchGraphNodeExecutorPort"
            )
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
        ):
            raise ValueError("research graph tenant_id must be non-empty when provided")
        if not isinstance(priority, ExecutionPriority):
            raise TypeError("research graph priority must be ExecutionPriority")
        self._plan = plan
        self._executor = executor
        self._pool = execution_pool or ResearchExecutionPool()
        self._owns_pool = execution_pool is None
        self._tenant_id = tenant_id
        self._priority = priority
        self._task_group_id = task_group_id
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
        group = self._pool.open_orchestration_group(
            self._task_group_id
            or f"research-graph:{self._plan.graph_id}:{uuid4().hex}",
            tenant_id=self._tenant_id,
            resource_id=f"research-graph:{self._plan.graph_id}",
            priority=self._priority,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        pending = {node.node_id: node for node in self._plan.nodes}
        running: dict[str, tuple[ResearchGraphNode, object]] = {}
        results: dict[str, ResearchGraphNodeResult] = {}

        def submit(node: ResearchGraphNode):
            def run(context, owned_node=node):
                context.checkpoint()
                self._executor.execute(
                    context,
                    owned_node,
                    deadline=deadline,
                )
                context.checkpoint()

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

                completed = tuple(
                    sorted(
                        node_id
                        for node_id, (_node, handle) in running.items()
                        if handle.done()
                    )
                )
                if completed:
                    for node_id in completed:
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

                sleep_seconds = 0.005
                if deadline is not None:
                    sleep_seconds = min(
                        sleep_seconds,
                        max(0.0, deadline.remaining_seconds),
                    )
                if sleep_seconds > 0.0:
                    time.sleep(sleep_seconds)

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
        if self._owns_pool:
            self._pool.close(deadline=deadline)

    def __enter__(self) -> "ResearchGraphScheduler":
        if self._closed:
            raise RuntimeError("research graph scheduler is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = ["ResearchGraphScheduler"]
