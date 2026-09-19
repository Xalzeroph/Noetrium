from __future__ import annotations

from dataclasses import replace
import time

import pytest

from noetrium.platform import (
    bind_research_campaign,
    bind_research_execution_pool,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.research.experimentation.api import (
    ResearchCampaignLaneState,
    ResearchCampaignPlan,
    ResearchCampaignStudy,
    ResearchCampaignStudyBinding,
)
from noetrium_platform.research.experimentation.study.api import (
    ExperimentPlan,
    StudyConcurrencyPolicy,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.study.runtime import (
    DeterministicStudyAssignment,
)


def _plan(study_id: str) -> ExperimentPlan:
    policy = replace(
        StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=30.0,
        ),
        max_parallel_repetitions=2,
    )
    protocol = StudyProtocol(
        study_id,
        f"workload-{study_id}",
        (
            StudyVariantSpec(
                "treatment",
                VariantKind.TREATMENT,
                "candidate",
                "a" * 64,
            ),
        ),
        2,
        "b" * 64,
        ("score",),
        "c" * 64,
        ("standard",),
        policy,
    )
    bindings = (
        VariantBinding(
            protocol.variants[0],
            "d" * 64,
            f"provider-{study_id}",
            "none",
            "treatment",
        ),
    )
    return ExperimentPlan.compile(
        protocol,
        bindings,
        DeterministicStudyAssignment().assignments(protocol),
    )


class _SuccessAdapter:
    def execute_bound(self, unit, bindings, plan_digest):
        del bindings, plan_digest
        time.sleep(0.02)
        return tuple(
            StudyMetricObservation(
                assignment,
                (("score", 1.0),),
            )
            for assignment in unit.assignments
        )

    def execute_bound_variant(self, assignment, binding, plan_digest):
        del binding, plan_digest
        return StudyMetricObservation(assignment, (("score", 1.0),))


class _FailingAdapter:
    def execute_bound(self, unit, bindings, plan_digest):
        del unit, bindings, plan_digest
        time.sleep(0.01)
        raise RuntimeError("intentional lane failure")

    def execute_bound_variant(self, assignment, binding, plan_digest):
        del assignment, binding, plan_digest
        raise RuntimeError("intentional lane failure")


def test_campaign_identity_is_canonical_over_lane_order() -> None:
    alpha = ResearchCampaignStudy("alpha", "1" * 64, _plan("study-alpha"))
    beta = ResearchCampaignStudy("beta", "2" * 64, _plan("study-beta"))
    forward = ResearchCampaignPlan("search-lineage", (alpha, beta))
    reverse = ResearchCampaignPlan("search-lineage", (beta, alpha))
    assert forward.studies == reverse.studies
    assert forward.campaign_digest == reverse.campaign_digest


def test_campaign_rejects_duplicate_scientific_plan_under_multiple_lanes() -> None:
    plan = _plan("same-study")
    with pytest.raises(ValueError, match="duplicate scientific plans"):
        ResearchCampaignPlan(
            "invalid-campaign",
            (
                ResearchCampaignStudy("first", "3" * 64, plan),
                ResearchCampaignStudy("second", "3" * 64, plan),
            ),
        )


def test_campaign_executes_independent_studies_in_parallel_and_isolates_failure() -> None:
    success_plan = _plan("study-success")
    failure_plan = _plan("study-failure")
    campaign = ResearchCampaignPlan(
        "parallel-lineage",
        (
            ResearchCampaignStudy("failure", "4" * 64, failure_plan),
            ResearchCampaignStudy("success", "5" * 64, success_plan),
        ),
    )
    pool = bind_research_execution_pool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
    )
    try:
        binding = bind_research_campaign(
            campaign,
            (
                ResearchCampaignStudyBinding("success", _SuccessAdapter()),
                ResearchCampaignStudyBinding("failure", _FailingAdapter()),
            ),
            execution_pool=pool,
        )
        try:
            report = binding.execute()
        finally:
            binding.close()

        assert report.campaign_digest == campaign.campaign_digest
        assert report.succeeded_lane_ids == ("success",)
        assert report.failed_lane_ids == ("failure",)
        by_lane = {row.lane_id: row for row in report.lanes}
        assert by_lane["success"].state is ResearchCampaignLaneState.SUCCEEDED
        assert by_lane["success"].report is not None
        assert by_lane["success"].study_plan_digest == success_plan.plan_digest
        assert by_lane["success"].report.plan_digest == success_plan.plan_digest
        assert by_lane["failure"].state is ResearchCampaignLaneState.FAILED
        assert by_lane["failure"].failure_type == "RuntimeError"
        assert "intentional lane failure" in by_lane["failure"].failure_message
    finally:
        pool.close()
