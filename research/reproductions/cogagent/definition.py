from __future__ import annotations

from research.reproductions.contracts import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionDelta,
    ReproductionDeltaKind,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="cogagent",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="cogagent",
        title="CogAgent: A Visual Language Model for GUI Agents",
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2024/html/"
            "Hong_CogAgent_A_Visual_Language_Model_for_GUI_Agents_CVPR_2024_paper.html"
        ),
        year=2024,
        paper_revision="CVPR 2024 final",
    ),
    catalog=ReproductionCatalog(
        domains=("gui-agent", "multimodal"),
        families=("gui_agent", "multimodal", "visual_grounding"),
        priority=1,
        benchmark_ids=("mind2web",),
        platform_pressure=(
            "model/request",
            "environment/gui",
            "artifact/lineage",
            "experimentation/study",
        ),
        method_owned=(
            "dual-resolution GUI visual representation",
            "screenshot-only GUI policy",
            "candidate-element target selection and operation prediction",
        ),
        platform_owned=(
            "multimodal content references",
            "model binding and immutable checkpoint identity",
            "Mind2Web task cut and verifier",
            "measurement and evidence lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/cogagent/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/cogagent/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/cogagent/study.py",
        ),
    ),
    primary_executable="research/reproductions/cogagent/program.py",
    reported_results=(
        ReportedResult(
            claim_id="cogagent_mind2web_cross_task",
            metric_id="step_success_rate_percent",
            value=62.3,
            qualifiers={
                "benchmark": "Mind2Web",
                "split": "cross-task",
                "representation": "screenshot-only",
                "source": "CVPR 2024 Table 3",
            },
        ),
        ReportedResult(
            claim_id="cogagent_mind2web_cross_website",
            metric_id="step_success_rate_percent",
            value=54.0,
            qualifiers={
                "benchmark": "Mind2Web",
                "split": "cross-website",
                "representation": "screenshot-only",
                "source": "CVPR 2024 Table 3",
            },
        ),
        ReportedResult(
            claim_id="cogagent_mind2web_cross_domain",
            metric_id="step_success_rate_percent",
            value=59.4,
            qualifiers={
                "benchmark": "Mind2Web",
                "split": "cross-domain",
                "representation": "screenshot-only",
                "source": "CVPR 2024 Table 3",
            },
        ),
        ReportedResult(
            claim_id="cogagent_mind2web_overall",
            metric_id="step_success_rate_percent",
            value=58.2,
            qualifiers={
                "benchmark": "Mind2Web",
                "split": "overall",
                "representation": "screenshot-only",
                "source": "CVPR 2024 Table 3",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="llama2_70b_html_mind2web",
            description=(
                "LLaMA2-70B using HTML screen representation in the same "
                "Mind2Web comparison."
            ),
            qualifiers={
                "cross_task_step_success_percent": 55.8,
                "cross_website_step_success_percent": 51.6,
                "cross_domain_step_success_percent": 55.7,
                "overall_step_success_percent": 54.4,
                "source": "CVPR 2024 Table 3",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The MethodProgram reproduces paper-era screenshot-only GUI "
                "policy semantics while the dual-resolution CogAgent network is "
                "treated as a separately bound model artifact/provider rather "
                "than reimplemented inside the method package."
            ),
        ),
    ),
    blockers=(
        "the exact CVPR paper-era CogAgent-18B checkpoint must be materialized with immutable model identity",
        "matched AITW execution awaits an AITW benchmark cut with exact paper evaluator identity",
        "no matched CVPR execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)

__all__ = ["REPRODUCTION"]
