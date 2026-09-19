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
    package='self_refine',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='self-refine',
        title='Self-Refine: Iterative Refinement with Self-Feedback',
        paper_uri='https://papers.neurips.cc/paper_files/paper/2023/hash/91edff07232fb1b55a505a9e9f6c0ff3-Abstract-Conference.html',
        year=2023,
        paper_revision='NeurIPS 2023',
    ),
    catalog=ReproductionCatalog(
        domains=('reflection-self-correction', 'self-improvement'),
        families=('reflection', 'self_improvement', 'reasoning'),
        priority=2,
        benchmark_ids=('commongen',),
        platform_pressure=('participant/method', 'model/request', 'execution', 'experimentation/study'),
        method_owned=('init-feedback-iterate loop', 'task-specific feedback and stopping semantics'),
        platform_owned=('bounded method execution', 'model invocation', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/self_refine/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/self_refine/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/self_refine/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='direct_generation',
            description='same model and CommonGen prompt bundle without feedback/refinement iterations',
            qualifiers={},
        ),
    ),
    deltas=(
    ),
    blockers=(
        'paper-era text-davinci-003 provider artifact is no longer intrinsically reproducible without an archived model endpoint',
        'paper-era spaCy/NLTK lexical feedback post-processing artifacts remain to be content-addressed for exact historical replay',
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reference_self_refine.py', 'tests/test_scientific_self_refine_v1.py', 'tests/test_scientific_self_refine_commongen_method_program_v1.py', 'tests/test_scientific_commongen_benchmark_v1.py'),
)

__all__ = ["REPRODUCTION"]
