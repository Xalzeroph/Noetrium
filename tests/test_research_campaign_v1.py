from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.research.experimentation.api import (
    ResearchCampaignPlan,
    ResearchCampaignStudy,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    StudyConcurrencyPolicy,
    StudyExecutionPlan,
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
