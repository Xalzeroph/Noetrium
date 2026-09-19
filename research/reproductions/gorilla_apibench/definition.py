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
    package='gorilla_apibench',
    lifecycle=ReproductionLifecycle('catalogued'),
    identity=ReproductionIdentity(
        method_id='gorilla',
        title='Gorilla: Large Language Model Connected with Massive APIs',
        paper_uri='https://arxiv.org/abs/2305.15334',
        year=2023,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('tool-use', 'retrieval-knowledge'),
        families=('tool_use', 'retrieval', 'api_agent', 'training'),
        priority=1,
        benchmark_ids=(),
        platform_pressure=('participant/capability', 'data/query', 'model/request', 'execution', 'experimentation/study', 'observability/telemetry'),
        method_owned=('retrieval-conditioned API selection', 'retriever-aware training semantics', 'API invocation generation policy'),
        platform_owned=('capability descriptors', 'model invocation', 'query transport', 'bounded execution', 'evidence and evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/gorilla_apibench/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/gorilla_apibench/selection.py',
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
    scientific_tests=('tests/test_scientific_gorilla_apibench_v1.py',),
)

__all__ = ["REPRODUCTION"]
