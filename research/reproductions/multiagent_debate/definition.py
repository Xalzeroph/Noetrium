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
    package='multiagent_debate',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='multiagent-debate',
        title='Improving Factuality and Reasoning in Language Models through Multiagent Debate',
        paper_uri='https://arxiv.org/abs/2305.14325',
        year=2023,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('multi-agent', 'reasoning'),
        families=('multi_agent', 'debate', 'reasoning'),
        priority=1,
        benchmark_ids=('gsm8k',),
        platform_pressure=('execution/workflow', 'participant/agent', 'model/request', 'experimentation/study', 'observability/telemetry'),
        method_owned=('debate round protocol', 'peer-response injection policy', 'answer aggregation semantics'),
        platform_owned=('participant topology', 'message identity and transport', 'model invocation', 'round evidence', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/multiagent_debate/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/multiagent_debate/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/multiagent_debate/study.py',
        ),
    ),
    primary_executable="research/reproductions/multiagent_debate/program.py",
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=(),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)

__all__ = ["REPRODUCTION"]
