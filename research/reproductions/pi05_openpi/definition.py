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
    package='pi05_openpi',
    lifecycle=ReproductionLifecycle('catalogued'),
    identity=ReproductionIdentity(
        method_id='pi0.5',
        title='π0.5: a Vision-Language-Action Model with Open-World Generalization',
        paper_uri='https://arxiv.org/abs/2504.16054',
        year=2025,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('embodied-robotics', 'multimodal', 'training'),
        families=('embodied', 'vla', 'multimodal', 'robot_policy'),
        priority=1,
        benchmark_ids=(),
        platform_pressure=('participant/agent', 'environment/embodied', 'model/request', 'experimentation/study'),
        method_owned=('heterogeneous co-training semantics', 'discrete state tokenization', 'flow-based continuous action policy'),
        platform_owned=('multimodal embodied observation transport', 'continuous action ABI', 'model execution', 'trajectory evidence and evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/pi05_openpi/compatibility.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/pi05_openpi/fidelity.py',
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
    scientific_tests=('tests/test_scientific_pi05_openpi_v1.py',),
)

__all__ = ["REPRODUCTION"]
