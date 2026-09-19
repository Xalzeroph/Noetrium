from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/qlass_alfworld/branch.py',
        ),
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
    reported_results=(
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='sft_policy',
            description='SFT policy inference without Q-guided stepwise candidate selection',
            qualifiers={},
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
    scientific_tests=('tests/test_scientific_qlass_alfworld_v1.py', 'tests/test_scientific_qlass_method_program_v1.py'),
)

__all__ = ["REPRODUCTION"]
