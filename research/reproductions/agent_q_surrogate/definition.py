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
    package='agent_q_surrogate',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='agent-q',
        title='Agent Q: Advanced Reasoning and Learning for Autonomous AI Agents',
        paper_uri='https://arxiv.org/abs/2408.07199',
        year=2024,
        paper_revision='arXiv:2408.07199',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'reflection-self-correction', 'training', 'web-agents'),
        families=('tree_search', 'self_critique', 'preference_learning', 'web_agent'),
        priority=1,
        benchmark_ids=('webshop', 'webvoyager'),
        platform_pressure=('environment/web', 'model/request', 'model/assignment', 'experimentation/study', 'artifact/lineage'),
        method_owned=('guided MCTS semantics', 'actor-critic action ranking', 'terminal self-judging', 'search-derived preference-pair generation'),
        platform_owned=('source-lane provenance', 'benchmark cut identity', 'named model-role binding', 'environment execution evidence', 'study and artifact lineage'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/agent_q_surrogate/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/agent_q_surrogate/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('substitution'),
            description='surrogate implementation instead of author-official Agent Q source',
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind('substitution'),
            description='surrogate WebVoyager mechanism-conformance benchmark instead of the paper WebShop evaluation',
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='paper WebShop execution remains a separate reproduction lane pending exact benchmark/source binding',
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='surrogate actor and critic concrete model revisions remain unresolved',
        ),
    ),
    blockers=('author-official Agent Q executable source remains unresolved', 'paper WebShop benchmark source revision and exact 11000/1087 split cut are not yet source-bound in Noetrium', 'surrogate actor and critic immutable model revisions are not frozen', 'live WebVoyager websites and manual task semantics can drift over time'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_agent_q_surrogate_v1.py',),
)

__all__ = ["REPRODUCTION"]
