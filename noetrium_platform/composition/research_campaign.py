from __future__ import annotations

from collections.abc import Mapping
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
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority
from noetrium_platform.research.experimentation.api.campaign import (
    ResearchCampaignExecutionReport,
    ResearchCampaignLaneResult,
    ResearchCampaignLaneState,
    ResearchCampaignPlan,
    ResearchCampaignStudy,
    ResearchCampaignStudyBinding,
)
from noetrium_platform.research.experimentation.study.runtime import (
    BasicStudyMetricAggregator,
)
from noetrium_platform.research.experimentation.api.program import (
    ExperimentProgramBinding,
    compile_experiment_program,
)


class ResearchCampaignBinding:
    """Composition-only concurrent execution of independent frozen studies.

    Orchestration tasks run in the pool's orchestration domain. Every scientific
    study opens its own experiment-domain task group and remains authoritative
    for its own concurrency policy, measurements, and result evidence.
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
        handles = {}
        try:
            for study in self._plan.studies:
                binding = self._bindings[study.lane_id]

                def run(context, owned_study=study, owned_binding=binding):
                    return self._run_lane(
                        context,
                        owned_study,
                        owned_binding,
                        deadline,
                    )

                handles[study.lane_id] = group.submit(
                    ExecutionSpec(
                        task_id=f"campaign-lane:{self._plan.campaign_id}:{study.lane_id}",
                        lane_kind=ExecutionLaneKind.BLOCKING_IO,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    run,
                    deadline=deadline,
                )

            results: list[ResearchCampaignLaneResult] = []
            for study in self._plan.studies:
                handle = handles[study.lane_id]
                try:
                    timeout = None if deadline is None else max(
                        0.001, deadline.remaining_seconds
                    )
                    report = handle.result(timeout=timeout)
                    results.append(
                        ResearchCampaignLaneResult(
                            lane_id=study.lane_id,
                            research_plan_digest=study.research_plan_digest,
                            study_plan_digest=study.plan.plan_digest,
                            state=ResearchCampaignLaneState.SUCCEEDED,
                            report=report,
                        )
                    )
                except BaseException as exc:
                    handle.cancel()
                    description = describe_exception(exc)
                    results.append(
                        ResearchCampaignLaneResult(
                            lane_id=study.lane_id,
                            research_plan_digest=study.research_plan_digest,
                            study_plan_digest=study.plan.plan_digest,
                            state=ResearchCampaignLaneState.FAILED,
                            failure_type=type(exc).__name__,
                            failure_message=(
                                description.safe_message.strip()
                                or type(exc).__name__
                            ),
                        )
                    )
            return ResearchCampaignExecutionReport(
                campaign_id=self._plan.campaign_id,
                campaign_digest=self._plan.campaign_digest,
                lanes=tuple(results),
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
