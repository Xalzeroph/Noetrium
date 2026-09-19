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
    package='live_swe_agent',
    lifecycle=ReproductionLifecycle('catalogued'),
    identity=ReproductionIdentity(
        method_id='live-swe-agent',
        title='Live-SWE-agent: Can Software Engineering Agents Self-Evolve on the Fly?',
        paper_uri='https://arxiv.org/abs/2511.13646',
        year=2025,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('software-engineering', 'self-improvement'),
        families=('software_agent', 'self_evolution', 'runtime_adaptation'),
        priority=1,
        benchmark_ids=('swe-bench',),
        platform_pressure=('participant/agent', 'environment/software', 'execution', 'artifact/lineage', 'reliability/recovery', 'experimentation/workbench'),
        method_owned=('online scaffold evolution policy', 'runtime self-modification semantics'),
        platform_owned=('software environment', 'isolated execution', 'lineage', 'rollback and recovery', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/live_swe_agent/fidelity.py',
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
    scientific_tests=('tests/test_scientific_self_evolution_fidelity_v1.py',),
)

__all__ = ["REPRODUCTION"]
