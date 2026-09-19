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
    package='multiagent_debate',
    lifecycle=ReproductionLifecycle('catalogued'),
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
        benchmark_ids=(),
        platform_pressure=('execution/workflow', 'participant/agent', 'model/request', 'experimentation/study', 'observability/telemetry'),
        method_owned=('debate round protocol', 'peer-response injection policy', 'answer aggregation semantics'),
        platform_owned=('participant topology', 'message identity and transport', 'model invocation', 'round evidence', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/multiagent_debate/fidelity.py',
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
    scientific_tests=('tests/test_scientific_multiagent_debate_fidelity_v1.py',),
)

__all__ = ["REPRODUCTION"]
