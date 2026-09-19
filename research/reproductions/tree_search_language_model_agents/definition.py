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
    package='tree_search_language_model_agents',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='tree-search-language-model-agents',
        title='Tree Search for Language Model Agents',
        paper_uri='https://arxiv.org/abs/2407.01476',
        year=2024,
        paper_revision='arXiv:2407.01476',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'web-agents', 'evaluation-benchmarks'),
        families=('tree_search', 'web_agent', 'test_time_compute'),
        priority=2,
        benchmark_ids=('visualwebarena', 'webarena'),
        platform_pressure=('environment/web', 'environment/runtime', 'model/request', 'model/assignment', 'experimentation/study'),
        method_owned=('tree search policy', 'value-function search budget', 'partial trajectory reuse'),
        platform_owned=('model role binding', 'benchmark cut identity', 'environment lifecycle', 'evidence and metrics'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/tree_search_language_model_agents/branch.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/tree_search_language_model_agents/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/tree_search_language_model_agents/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='prompt_agent',
            description='same released VWA stack with prompt agent type and no tree search',
            qualifiers={},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='exact hosted model deployment identity remains partially unresolved',
        ),
    ),
    blockers=('exact hosted GPT-4o deployment snapshots are not fully content-addressed', 'matched browser service/config deployment remains to be bound'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_tree_search_language_model_agents_v1.py',),
)

__all__ = ["REPRODUCTION"]
