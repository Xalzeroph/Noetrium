from __future__ import annotations

from collections.abc import Mapping
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
from noetrium_platform.research.execution.policy.api import ExecutionPriority
from noetrium_platform.research.experimentation.api.campaign import (
    ResearchCampaignExecutionReport,
    ResearchCampaignLaneResult,
    ResearchCampaignLaneState,
    ResearchCampaignPlan,
    ResearchCampaignStudy,
    ResearchCampaignStudyBinding,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    BasicStudyMetricAggregator,
)
from noetrium_platform.research.experimentation.api.program import (
    ExperimentProgramBinding,
    compile_experiment_program,
)



def _reportable_failure(exc: BaseException) -> BaseException:
    # Collapse structured-concurrency wrappers when they contain one semantic failure.
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


class ResearchCampaignBinding:
    """Composition-only dependency-aware execution of frozen studies.

    Campaign dependencies gate orchestration eligibility only. Resource capacity
    remains owned by ResearchExecutionPool, while each scientific study retains
    authority over its own experiment concurrency, measurements, and evidence.
    """

    def __init__(
        self,
        plan: ResearchCampaignPlan,
        bindings: tuple[ResearchCampaignStudyBinding, ...],
        *,
        execution_pool: ResearchExecutionPool | None = None,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        task_group_id: str | None = None,
    ) -> None:
        if type(plan) is not ResearchCampaignPlan:
            raise TypeError("research campaign requires ResearchCampaignPlan")
        if type(bindings) is not tuple or any(
            type(row) is not ResearchCampaignStudyBinding for row in bindings
        ):
            raise TypeError("campaign bindings must be ResearchCampaignStudyBinding tuple")
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
        ):
            raise ValueError("campaign tenant_id must be non-empty when provided")
        if not isinstance(priority, ExecutionPriority):
            raise TypeError("campaign priority must be ExecutionPriority")
        by_lane: dict[str, ResearchCampaignStudyBinding] = {}
        for binding in bindings:
            if binding.lane_id in by_lane:
                raise ValueError("campaign runtime binding lane identities must be unique")
            by_lane[binding.lane_id] = binding
        expected = {row.lane_id for row in plan.studies}
        if set(by_lane) != expected:
            missing = sorted(expected - set(by_lane))
            extra = sorted(set(by_lane) - expected)
            raise ValueError(
                f"campaign runtime bindings must exactly cover frozen lanes; missing={missing} extra={extra}"
            )
        self._plan = plan
        self._bindings: Mapping[str, ResearchCampaignStudyBinding] = by_lane
        self._pool = execution_pool or ResearchExecutionPool()
        self._owns_pool = execution_pool is None
        self._tenant_id = tenant_id
        self._priority = priority
        self._task_group_id = task_group_id
        self._closed = False

    @property
    def plan(self) -> ResearchCampaignPlan:
        return self._plan

    def _run_lane(
        self,
        context,
        study: ResearchCampaignStudy,
        binding: ResearchCampaignStudyBinding,
        deadline: Deadline | None,
    ):
        context.checkpoint()
        group = self._pool.open_experiment_group(
            f"campaign-study:{self._plan.campaign_id}:{study.lane_id}:{uuid4().hex}",
            tenant_id=self._tenant_id,
            resource_id=f"study:{study.plan.protocol.study_id}",
            priority=self._priority,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.FAIL_FAST,
        )
        try:
            aggregator = binding.aggregation or BasicStudyMetricAggregator()
            report = ExperimentProgramBinding(
                compile_experiment_program(study.plan),
                binding.adapter,
                aggregator,
                task_group=group,
            ).execute(
                machine_id=(
                    f"campaign-experiment:{self._plan.campaign_id}:"
                    f"{study.lane_id}:{study.plan.plan_digest[:16]}"
                ),
            )
            context.checkpoint()
            return report
        finally:
            self._pool.close_experiment_group(group, deadline=deadline)

    def execute(
        self,
        *,
        deadline: Deadline | None = None,
    ) -> ResearchCampaignExecutionReport:
        if self._closed:
            raise RuntimeError("research campaign binding is closed")
        group = self._pool.open_orchestration_group(
            self._task_group_id
            or f"research-campaign:{self._plan.campaign_id}:{uuid4().hex}",
            tenant_id=self._tenant_id,
            resource_id=f"campaign:{self._plan.campaign_id}",
            priority=self._priority,
            deadline=deadline,
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        pending = {study.lane_id: study for study in self._plan.studies}
        running = {}
        results: dict[str, ResearchCampaignLaneResult] = {}

        def submit(study: ResearchCampaignStudy):
            binding = self._bindings[study.lane_id]

            def run(context, owned_study=study, owned_binding=binding):
                return self._run_lane(
                    context,
                    owned_study,
                    owned_binding,
                    deadline,
                )

            return group.submit(
                ExecutionSpec(
                    task_id=(
                        f"campaign-lane:{self._plan.campaign_id}:"
                        f"{study.lane_id}"
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                run,
                deadline=deadline,
            )

        def record_completion(lane_id: str, *, timeout: float | None = None) -> None:
            study, handle = running.pop(lane_id)
            try:
                report = handle.result(timeout=timeout)
                results[lane_id] = ResearchCampaignLaneResult(
                    lane_id=study.lane_id,
                    research_plan_digest=study.research_plan_digest,
                    study_plan_digest=study.plan.plan_digest,
                    state=ResearchCampaignLaneState.SUCCEEDED,
                    report=report,
                )
            except BaseException as exc:
                handle.cancel()
                failure = _reportable_failure(exc)
                description = describe_exception(failure)
                results[lane_id] = ResearchCampaignLaneResult(
                    lane_id=study.lane_id,
                    research_plan_digest=study.research_plan_digest,
                    study_plan_digest=study.plan.plan_digest,
                    state=ResearchCampaignLaneState.FAILED,
                    failure_type=type(failure).__name__,
                    failure_message=(
                        description.safe_message.strip()
                        or type(failure).__name__
                    ),
                )

        try:
            while pending or running:
                progressed = False

                for lane_id in tuple(sorted(pending)):
                    study = pending[lane_id]
                    blockers = tuple(
                        dependency
                        for dependency in study.depends_on_lane_ids
                        if dependency in results
                        and results[dependency].state
                        in {
                            ResearchCampaignLaneState.FAILED,
                            ResearchCampaignLaneState.BLOCKED,
                        }
                    )
                    if not blockers:
                        continue
                    results[lane_id] = ResearchCampaignLaneResult(
                        lane_id=study.lane_id,
                        research_plan_digest=study.research_plan_digest,
                        study_plan_digest=study.plan.plan_digest,
                        state=ResearchCampaignLaneState.BLOCKED,
                        blocked_by_lane_ids=blockers,
                    )
                    del pending[lane_id]
                    progressed = True

                for lane_id in tuple(sorted(pending)):
                    study = pending[lane_id]
                    if not all(
                        dependency in results
                        and results[dependency].state
                        is ResearchCampaignLaneState.SUCCEEDED
                        for dependency in study.depends_on_lane_ids
                    ):
                        continue
                    running[lane_id] = (study, submit(study))
                    del pending[lane_id]
                    progressed = True

                completed = tuple(
                    sorted(
                        lane_id
                        for lane_id, (_study, handle) in running.items()
                        if handle.done()
                    )
                )
                if completed:
                    for lane_id in completed:
                        record_completion(lane_id)
                    continue

                if pending and not running and not progressed:
                    raise RuntimeError(
                        "campaign scheduler reached an impossible dependency state"
                    )

                if not running:
                    continue

                if deadline is not None and deadline.expired:
                    for lane_id in tuple(sorted(running)):
                        record_completion(lane_id, timeout=0.0)
                    continue

                sleep_seconds = 0.005
                if deadline is not None:
                    sleep_seconds = min(
                        sleep_seconds,
                        max(0.0, deadline.remaining_seconds),
                    )
                if sleep_seconds > 0.0:
                    time.sleep(sleep_seconds)

            return ResearchCampaignExecutionReport(
                campaign_id=self._plan.campaign_id,
                campaign_digest=self._plan.campaign_digest,
                lanes=tuple(results[lane_id] for lane_id in sorted(results)),
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

    def __enter__(self) -> "ResearchCampaignBinding":
        if self._closed:
            raise RuntimeError("research campaign binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = ["ResearchCampaignBinding"]
