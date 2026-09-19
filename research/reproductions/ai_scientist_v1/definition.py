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
    package='ai_scientist_v1',
    lifecycle=ReproductionLifecycle('catalogued'),
    identity=ReproductionIdentity(
        method_id='ai-scientist',
        title='The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery',
        paper_uri='https://arxiv.org/abs/2408.06292',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('scientific-research', 'self-improvement'),
        families=('scientific_agent', 'experimentation', 'code_execution', 'paper_writing', 'review'),
        priority=1,
        benchmark_ids=(),
        platform_pressure=('environment/software', 'model/request', 'experimentation/study', 'experimentation/workbench', 'artifact/lineage', 'reliability/recovery'),
        method_owned=('idea generation and novelty policy', 'template-bound experiment editing loop', 'writeup and review policy'),
        platform_owned=('isolated project execution', 'experiment identity and metrics', 'artifact lineage', 'parallel resource scheduling', 'recovery and evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/ai_scientist_v1/fidelity.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=(),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_ai_scientist_family_v1.py',),
)

__all__ = ["REPRODUCTION"]
