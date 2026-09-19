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
    package='reflexion_alfworld',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='reflexion',
        title='Reflexion: Language Agents with Verbal Reinforcement Learning',
        paper_uri='https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html',
        year=2023,
        paper_revision='NeurIPS 2023 / arXiv:2303.11366',
    ),
    catalog=ReproductionCatalog(
        domains=('reflection-self-correction', 'memory', 'self-improvement'),
        families=('reflection', 'memory', 'agent_loop'),
        priority=1,
        benchmark_ids=('alfworld',),
        platform_pressure=('participant/agent', 'model/request', 'model/assignment', 'environment/text_world', 'experimentation/study'),
        method_owned=('failed-trial verbal reflection policy', 'per-task reflection memory semantics', 'multi-trial retry policy'),
        platform_owned=('named model-role binding', 'benchmark cut identity', 'environment lifecycle', 'study execution and evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/reflexion_alfworld/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/reflexion_alfworld/memory.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('semantics'),
            path='research/reproductions/reflexion_alfworld/semantics.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/reflexion_alfworld/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/reflexion_alfworld/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='historical hosted model snapshots are unavailable as immutable public artifacts',
        ),
    ),
    blockers=('historical action/reflection model serving snapshots are not exact-current deployments', 'exact ALFWorld dataset/runtime deployment cut must be bound before matched execution'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reflexion_alfworld_fidelity_v1.py', 'tests/test_scientific_reflexion_alfworld_v1.py', 'tests/test_scientific_reflexion_method_program_v1.py'),
)

__all__ = ["REPRODUCTION"]
