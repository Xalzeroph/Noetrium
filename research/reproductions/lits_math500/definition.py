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
    package='lits_math500',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='lits',
        title='LiTS: A Modular Framework for LLM Tree Search',
        paper_uri='https://arxiv.org/abs/2603.00631',
        year=2026,
        paper_revision='arXiv:2603.00631v1 / ACL 2026 Demo',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'reasoning', 'runtime-systems'),
        families=('tree_search', 'reasoning', 'modular_search', 'tool_use'),
        priority=1,
        benchmark_ids=('math500',),
        platform_pressure=('model/request', 'model/assignment', 'execution', 'experimentation/study', 'observability/telemetry'),
        method_owned=('Policy/Transition/RewardModel decomposition', 'MCTS/BFS search semantics', 'component registration and composition policy'),
        platform_owned=('named model-role binding', 'benchmark cut identity', 'bounded method execution', 'measurements and evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/lits_math500/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/lits_math500/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='concrete model identity is intentionally external to the released example and must be declared by an executable study lane',
        ),
    ),
    blockers=('the released MATH500 example does not freeze one concrete model provider/revision, so matched paper-result execution requires an explicit model lane selection',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_lits_math500_v1.py',),
)

__all__ = ["REPRODUCTION"]
