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
    package='tree_of_thoughts',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='tree-of-thoughts',
        title='Tree of Thoughts: Deliberate Problem Solving with Large Language Models',
        paper_uri='https://proceedings.neurips.cc/paper/2023/hash/271db9922b8d1f4dd7aaef84ed5ac703-Abstract.html',
        year=2023,
        paper_revision='arXiv:2305.10601 / NeurIPS 2023',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'reasoning'),
        families=('tree_search', 'reasoning'),
        priority=1,
        benchmark_ids=('game24',),
        platform_pressure=('model/request', 'model/assignment', 'experimentation/study', 'experimentation/evaluation'),
        method_owned=('thought generation policy', 'thought evaluation policy', 'frontier selection policy'),
        platform_owned=('named model-role binding', 'benchmark cut identity', 'study expansion', 'evaluation evidence and measurements'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/tree_of_thoughts/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/tree_of_thoughts/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/tree_of_thoughts/search.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/tree_of_thoughts/study.py',
        ),
    ),
    primary_executable="research/reproductions/tree_of_thoughts/program.py",
    reported_results=(
        ReportedResult(
            claim_id="tot_gpt4_game24",
            metric_id="success_rate_percent",
            value=74.0,
            qualifiers={
                "benchmark": "Game of 24",
                "model": "GPT-4",
                "method": "Tree of Thoughts",
                "source": "NeurIPS 2023 abstract and Game of 24 evaluation",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="cot_gpt4_game24",
            description=(
                "GPT-4 chain-of-thought prompting on the same Game of 24 "
                "evaluation reported by the Tree of Thoughts paper."
            ),
            qualifiers={
                "success_rate_percent": 4.0,
                "benchmark": "Game of 24",
                "model": "GPT-4",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='historical hosted GPT-4 snapshot identity remains unresolved',
        ),
    ),
    blockers=('exact historical GPT-4 serving snapshot is not available as an immutable public model artifact',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_tree_of_thoughts_fidelity_v1.py',),
)

__all__ = ["REPRODUCTION"]
