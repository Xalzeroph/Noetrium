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
    package='lats_webshop',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='lats',
        title='Language Agent Tree Search Unifies Reasoning, Acting, and Planning in Language Models',
        paper_uri='https://proceedings.mlr.press/v235/zhou24r.html',
        year=2024,
        paper_revision='arXiv:2310.04406 / ICML 2024',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'reflection-self-correction', 'tool-use'),
        families=('tree_search', 'reflection', 'web_agent'),
        priority=1,
        benchmark_ids=('webshop',),
        platform_pressure=('environment/web', 'environment/runtime', 'model/request', 'model/assignment', 'experimentation/study'),
        method_owned=('UCT tree policy', 'LM value estimation', 'failed-trajectory reflection policy', 'branch search semantics'),
        platform_owned=('branchable environment lifecycle', 'named model-role binding', 'benchmark cut identity', 'study execution and evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/lats_webshop/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/lats_webshop/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/lats_webshop/reflection.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/lats_webshop/study.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/lats_webshop/tree.py',
        ),
    ),
    primary_executable="research/reproductions/lats_webshop/program.py",
    reported_results=(
        ReportedResult(
            claim_id="lats_webshop_average_score",
            metric_id="average_score",
            value=75.9,
            qualifiers={
                "benchmark": "WebShop",
                "model": "GPT-3.5",
                "method": "LATS",
                "source": "ICML 2024 WebShop evaluation",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="react_webshop",
            description=(
                "ReAct prompting baseline on the same WebShop evaluation."
            ),
            qualifiers={
                "average_score": 53.8,
                "success_rate_percent": 28.0,
                "source": "ICML 2024 WebShop evaluation",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='exact paper-era executable source cut predating the later released repository cut has not been frozen',
        ),
    ),
    blockers=('the audited executable cut post-dates the original paper', 'exact historical gpt-3.5-turbo serving snapshot is unresolved', 'branch-restorable WebShop environment binding is not yet matched'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_lats_webshop_v1.py',),
)

__all__ = ["REPRODUCTION"]
