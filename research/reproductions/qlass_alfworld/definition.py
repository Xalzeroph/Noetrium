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
    package='qlass_alfworld',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='qlass',
        title='QLASS: Boosting Language Agent Inference via Q-Guided Stepwise Search',
        paper_uri='https://proceedings.mlr.press/v267/lin25l.html',
        year=2025,
        paper_revision='arXiv:2502.02584 / ICML 2025',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'training', 'evaluation-benchmarks'),
        families=('planning', 'search', 'q_guided_inference', 'process_reward'),
        priority=1,
        benchmark_ids=('alfworld', 'webshop'),
        platform_pressure=('environment/text_world', 'model/request', 'model/assignment', 'experimentation/study', 'artifact/lineage'),
        method_owned=('stepwise best-of-N action search', 'Q-Net trajectory value estimation', 'Q-guided candidate selection', 'self-exploration and Q-training semantics'),
        platform_owned=('benchmark cut identity', 'named model-role binding', 'environment execution and replay evidence', 'study expansion and measurements'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/qlass_alfworld/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/qlass_alfworld/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/qlass_alfworld/study.py',
        ),
    ),
    primary_executable="research/reproductions/qlass_alfworld/program.py",
    reported_results=(
        ReportedResult(
            claim_id="qlass_alfworld_seen_reward",
            metric_id="average_reward",
            value=77.9,
            qualifiers={
                "benchmark": "ALFWorld",
                "split": "seen",
                "base_model": "Llama-2-7B-Chat",
                "source": "ICML 2025 Table 2",
            },
        ),
        ReportedResult(
            claim_id="qlass_alfworld_unseen_reward",
            metric_id="average_reward",
            value=82.8,
            qualifiers={
                "benchmark": "ALFWorld",
                "split": "unseen",
                "base_model": "Llama-2-7B-Chat",
                "source": "ICML 2025 Table 2",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='sft_policy',
            description='SFT policy inference without Q-guided stepwise candidate selection',
            qualifiers={
                "alfworld_seen_average_reward": 60.0,
                "alfworld_unseen_average_reward": 67.2,
                "source": "ICML 2025 Table 2",
            },
        ),
        ReferenceBaseline(
            baseline_id="eto_policy",
            description=(
                "ETO trajectory-level preference optimization baseline on "
                "the same ALFWorld evaluation."
            ),
            qualifiers={
                "alfworld_seen_average_reward": 68.6,
                "alfworld_unseen_average_reward": 72.4,
                "source": "ICML 2025 Table 2",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='exact model artifact revisions/checkpoint digests for the released SFT policy and Q-Net are not yet bound',
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='released launcher is not runnable as written under its documented four-GPU assumption without correcting model-name and evaluator GPU mapping',
        ),
    ),
    blockers=('paper-era source cut contains no executable training/evaluation implementation', 'released policy and Q-Net model artifact revisions are not yet content-addressed in Noetrium', 'matched ALFWorld dev deployment remains to be bound', 'released launcher references undefined explore_model_name when passing --model_name', 'released four-slice evaluator maps CUDA devices to 1,2,3,4 while the documented four-GPU server allocation is 0,1,2,3'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)

__all__ = ["REPRODUCTION"]
