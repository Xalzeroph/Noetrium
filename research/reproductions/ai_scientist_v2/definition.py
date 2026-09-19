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
    package='ai_scientist_v2',
    lifecycle=ReproductionLifecycle('catalogued'),
    identity=ReproductionIdentity(
        method_id='ai-scientist-v2',
        title='The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search',
        paper_uri='https://arxiv.org/abs/2504.08066',
        year=2025,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('scientific-research', 'planning-search', 'self-improvement', 'runtime-systems'),
        families=('scientific_agent', 'tree_search', 'experimentation', 'code_execution', 'paper_writing', 'review'),
        priority=1,
        benchmark_ids=(),
        platform_pressure=('environment/software', 'model/request', 'experimentation/study', 'experimentation/workbench', 'artifact/lineage', 'reliability/recovery', 'resource'),
        method_owned=('progressive agentic tree-search policy', 'experiment-manager guidance', 'citation and multimodal review policy', 'downstream method journal'),
        platform_owned=('isolated branch execution', 'experiment identity and metrics', 'resource scheduling', 'artifact lineage', 'Kernel Journal facts', 'recovery and evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/ai_scientist_v2/fidelity.py',
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
