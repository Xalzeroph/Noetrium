from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from uuid import uuid4

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    TaskFailurePolicy,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphNode,
    ResearchGraphNodeState,
    ResearchGraphPlan,
)
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
from noetrium_platform.composition.research_graph import ResearchGraphScheduler



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

        studies = {study.lane_id: study for study in self._plan.studies}
        lane_reports = {}
        report_lock = RLock()
        owner = self

        class CampaignNodeExecutor:
            def execute(self, context, node: ResearchGraphNode, *, deadline):
                study = studies[node.node_id]
                report = owner._run_lane(
                    context,
                    study,
                    owner._bindings[study.lane_id],
                    deadline,
                )
                with report_lock:
                    lane_reports[node.node_id] = report

        graph = ResearchGraphPlan(
            self._plan.campaign_id,
            self._plan.campaign_digest,
            tuple(
                ResearchGraphNode(
                    study.lane_id,
                    study.study_digest,
                    study.depends_on_lane_ids,
                )
                for study in self._plan.studies
            ),
        )
        scheduler = ResearchGraphScheduler(
            graph,
            CampaignNodeExecutor(),
            execution_pool=self._pool,
            tenant_id=self._tenant_id,
            priority=self._priority,
            task_group_id=self._task_group_id,
        )
        try:
            graph_report = scheduler.execute(deadline=deadline)
        finally:
            scheduler.close(deadline=deadline)

        lanes = []
        for result in graph_report.nodes:
            study = studies[result.node_id]
            if result.state is ResearchGraphNodeState.SUCCEEDED:
                with report_lock:
                    report = lane_reports[result.node_id]
                lanes.append(
                    ResearchCampaignLaneResult(
                        lane_id=study.lane_id,
                        research_plan_digest=study.research_plan_digest,
                        study_plan_digest=study.plan.plan_digest,
                        state=ResearchCampaignLaneState.SUCCEEDED,
                        report=report,
                    )
                )
            elif result.state is ResearchGraphNodeState.FAILED:
                lanes.append(
                    ResearchCampaignLaneResult(
                        lane_id=study.lane_id,
                        research_plan_digest=study.research_plan_digest,
                        study_plan_digest=study.plan.plan_digest,
                        state=ResearchCampaignLaneState.FAILED,
                        failure_type=result.failure_type,
                        failure_message=result.failure_message,
                    )
                )
            else:
                lanes.append(
                    ResearchCampaignLaneResult(
                        lane_id=study.lane_id,
                        research_plan_digest=study.research_plan_digest,
                        study_plan_digest=study.plan.plan_digest,
                        state=ResearchCampaignLaneState.BLOCKED,
                        blocked_by_lane_ids=result.blocked_by_node_ids,
                    )
                )

        return ResearchCampaignExecutionReport(
            campaign_id=self._plan.campaign_id,
            campaign_digest=self._plan.campaign_digest,
            lanes=tuple(lanes),
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
