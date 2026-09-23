from __future__ import annotations

from dataclasses import replace
import time

import pytest

from noetrium_platform.platform import (
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
from noetrium_platform.research.experimentation.lifecycle.api import (
    StudyExecutionPlan,
    StudyConcurrencyPolicy,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    DeterministicStudyAssignment,
)


def _plan(study_id: str, *, repetitions: int = 2) -> StudyExecutionPlan:
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
        repetitions,
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
    return StudyExecutionPlan.compile(
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


class _RecordingAdapter:
    def __init__(
        self,
        lane_id: str,
        events: dict[str, float],
        *,
        delay: float = 0.0,
        fail: bool = False,
    ) -> None:
        self._lane_id = lane_id
        self._events = events
        self._delay = delay
        self._fail = fail

    def execute_bound(self, unit, bindings, plan_digest):
        del bindings, plan_digest
        self._events[f"{self._lane_id}.start"] = time.monotonic()
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise RuntimeError(f"{self._lane_id} failed")
        self._events[f"{self._lane_id}.end"] = time.monotonic()
        return tuple(
            StudyMetricObservation(
                assignment,
                (("score", 1.0),),
            )
            for assignment in unit.assignments
        )

    def execute_bound_variant(self, assignment, binding, plan_digest):
        del binding, plan_digest
        self._events[f"{self._lane_id}.start"] = time.monotonic()
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise RuntimeError(f"{self._lane_id} failed")
        self._events[f"{self._lane_id}.end"] = time.monotonic()
        return StudyMetricObservation(assignment, (("score", 1.0),))


def test_campaign_identity_is_canonical_over_lane_order() -> None:
    alpha = ResearchCampaignStudy("alpha", "1" * 64, _plan("study-alpha"))
    beta = ResearchCampaignStudy("beta", "2" * 64, _plan("study-beta"))
    forward = ResearchCampaignPlan("search-lineage", (alpha, beta))
    reverse = ResearchCampaignPlan("search-lineage", (beta, alpha))
    assert forward.studies == reverse.studies
    assert forward.campaign_digest == reverse.campaign_digest


def test_campaign_rejects_duplicate_scientific_plan_under_multiple_lanes() -> None:
    plan = _plan("same-study")
    with pytest.raises(ValueError, match="duplicate compiled research plans"):
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


def test_campaign_dependency_graph_is_frozen_validated_and_digest_bound() -> None:
    alpha_plan = _plan("study-alpha", repetitions=1)
    beta_plan = _plan("study-beta", repetitions=1)

    alpha = ResearchCampaignStudy("alpha", "6" * 64, alpha_plan)
    beta = ResearchCampaignStudy(
        "beta",
        "7" * 64,
        beta_plan,
        ("alpha",),
    )
    graph = ResearchCampaignPlan("dependency-identity", (beta, alpha))
    independent = ResearchCampaignPlan(
        "dependency-identity",
        (
            alpha,
            ResearchCampaignStudy("beta", "7" * 64, beta_plan),
        ),
    )

    assert graph.studies[1].depends_on_lane_ids == ("alpha",)
    assert graph.campaign_digest != independent.campaign_digest

    with pytest.raises(ValueError, match="unknown lanes"):
        ResearchCampaignPlan(
            "unknown-dependency",
            (
                ResearchCampaignStudy(
                    "alpha",
                    "8" * 64,
                    alpha_plan,
                    ("missing",),
                ),
            ),
        )

    with pytest.raises(ValueError, match="cannot depend on itself"):
        ResearchCampaignStudy(
            "alpha",
            "8" * 64,
            alpha_plan,
            ("alpha",),
        )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        ResearchCampaignStudy(
            "alpha",
            "8" * 64,
            alpha_plan,
            ("beta", "beta"),
        )

    with pytest.raises(ValueError, match="dependency cycle"):
        ResearchCampaignPlan(
            "cyclic-dependency",
            (
                ResearchCampaignStudy(
                    "alpha",
                    "8" * 64,
                    alpha_plan,
                    ("beta",),
                ),
                ResearchCampaignStudy(
                    "beta",
                    "9" * 64,
                    beta_plan,
                    ("alpha",),
                ),
            ),
        )


def test_campaign_launches_newly_ready_lane_without_waiting_for_unrelated_lane() -> None:
    events: dict[str, float] = {}
    root_plan = _plan("study-root", repetitions=1)
    child_plan = _plan("study-child", repetitions=1)
    independent_plan = _plan("study-independent", repetitions=1)
    campaign = ResearchCampaignPlan(
        "dependency-scheduling",
        (
            ResearchCampaignStudy("root", "a" * 64, root_plan),
            ResearchCampaignStudy(
                "child",
                "b" * 64,
                child_plan,
                ("root",),
            ),
            ResearchCampaignStudy(
                "independent",
                "c" * 64,
                independent_plan,
            ),
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
                ResearchCampaignStudyBinding(
                    "root",
                    _RecordingAdapter("root", events, delay=0.04),
                ),
                ResearchCampaignStudyBinding(
                    "child",
                    _RecordingAdapter("child", events, delay=0.01),
                ),
                ResearchCampaignStudyBinding(
                    "independent",
                    _RecordingAdapter("independent", events, delay=0.15),
                ),
            ),
            execution_pool=pool,
        )
        try:
            report = binding.execute()
        finally:
            binding.close()

        assert report.failed_lane_ids == ()
        assert report.blocked_lane_ids == ()
        assert report.succeeded_lane_ids == ("child", "independent", "root")
        assert events["child.start"] >= events["root.end"]
        assert events["child.start"] < events["independent.end"]
    finally:
        pool.close()


def test_campaign_failure_blocks_descendants_but_not_independent_branches() -> None:
    events: dict[str, float] = {}
    root_plan = _plan("study-root-failure", repetitions=1)
    child_plan = _plan("study-child-blocked", repetitions=1)
    grandchild_plan = _plan("study-grandchild-blocked", repetitions=1)
    independent_plan = _plan("study-independent-success", repetitions=1)
    campaign = ResearchCampaignPlan(
        "dependency-failure-propagation",
        (
            ResearchCampaignStudy("root", "d" * 64, root_plan),
            ResearchCampaignStudy(
                "child",
                "e" * 64,
                child_plan,
                ("root",),
            ),
            ResearchCampaignStudy(
                "grandchild",
                "f" * 64,
                grandchild_plan,
                ("child",),
            ),
            ResearchCampaignStudy(
                "independent",
                "1" * 64,
                independent_plan,
            ),
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
                ResearchCampaignStudyBinding(
                    "root",
                    _RecordingAdapter("root", events, delay=0.01, fail=True),
                ),
                ResearchCampaignStudyBinding(
                    "child",
                    _RecordingAdapter("child", events),
                ),
                ResearchCampaignStudyBinding(
                    "grandchild",
                    _RecordingAdapter("grandchild", events),
                ),
                ResearchCampaignStudyBinding(
                    "independent",
                    _RecordingAdapter("independent", events, delay=0.02),
                ),
            ),
            execution_pool=pool,
        )
        try:
            report = binding.execute()
        finally:
            binding.close()

        assert report.failed_lane_ids == ("root",)
        assert report.blocked_lane_ids == ("child", "grandchild")
        assert report.succeeded_lane_ids == ("independent",)
        by_lane = {row.lane_id: row for row in report.lanes}
        assert by_lane["child"].state is ResearchCampaignLaneState.BLOCKED
        assert by_lane["child"].blocked_by_lane_ids == ("root",)
        assert by_lane["grandchild"].blocked_by_lane_ids == ("child",)
        assert "child.start" not in events
        assert "grandchild.start" not in events
        assert "independent.end" in events
    finally:
        pool.close()
