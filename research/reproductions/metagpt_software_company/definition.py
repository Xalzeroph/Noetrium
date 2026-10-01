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
    ReproductionMethodConfigurerBinding,
)

REPRODUCTION = ReproductionDefinition(
    package='metagpt_software_company',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='metagpt',
        title='MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework',
        paper_uri='https://proceedings.iclr.cc/paper_files/paper/2024/hash/6507b115562bb0a305f1958ccc87355a-Abstract-Conference.html',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('multi-agent', 'software-engineering'),
        families=('multi_agent', 'software_agent', 'sop', 'artifact_pipeline'),
        priority=1,
        benchmark_ids=('humaneval',),
        platform_pressure=('execution/workflow', 'participant/agent', 'environment/software', 'artifact/lineage', 'execution', 'experimentation/study'),
        method_owned=('software-company role specialization', 'SOP dependency graph', 'artifact-to-role workflow semantics'),
        platform_owned=('participant topology', 'message transport', 'software workspace execution', 'artifact lineage', 'bounded orchestration', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/metagpt_software_company/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/metagpt_software_company/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/metagpt_software_company/study.py',
        ),
    ),
    method_configurer=ReproductionMethodConfigurerBinding(
        qualname="build_metagpt_software_company_method_program",
        kwargs={"use_code_review": False},
    ),
    primary_executable="research/reproductions/metagpt_software_company/program.py",
    reported_results=(
        ReportedResult(
            claim_id="metagpt_mbpp_executive_feedback_gain",
            metric_id="absolute_improvement_points",
            value=5.4,
            qualifiers={
                "benchmark": "mbpp",
                "mechanism": "executive-feedback",
                "source": "ICLR-2024 paper",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="metagpt_without_executive_feedback",
            description=(
                "MetaGPT ablation without executive feedback used to quantify "
                "the MBPP improvement from the feedback mechanism."
            ),
            qualifiers={"source": "ICLR-2024 paper evaluation"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The typed executable Study currently binds the 164-task "
                "HumanEval cut, while the recorded paper claim is the MBPP "
                "executive-feedback ablation. HumanEval execution evidence "
                "must not be used to qualify the MBPP claim."
            ),
        ),
    ),
    blockers=(
        "the paper MBPP executive-feedback benchmark cut and evaluator are not "
        "yet bound as an executable Study",
        "the exact paper-era hosted model service revisions used for the MBPP "
        "ablation are not immutable public model artifacts",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_metagpt_fidelity_v1.py', 'tests/test_scientific_humaneval_cut_v1.py'),
)

__all__ = ["REPRODUCTION"]
