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
    package='memgpt_classic',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='memgpt',
        title='MemGPT: Towards LLMs as Operating Systems',
        paper_uri='https://arxiv.org/abs/2310.08560',
        year=2023,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('memory', 'context-management', 'runtime-systems'),
        families=('memory', 'context_management', 'long_horizon'),
        priority=1,
        benchmark_ids=('memoryarena',),
        platform_pressure=('model/request', 'participant/agent', 'data/state', 'data/projection', 'data/query', 'artifact/lineage', 'reliability/recovery'),
        method_owned=('memory hierarchy semantics', 'memory movement policy'),
        platform_owned=('context admission', 'durable state', 'semantic projection and query', 'lineage', 'checkpoint and recovery'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/memgpt_classic/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('semantics'),
            path='research/reproductions/memgpt_classic/semantics.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/memgpt_classic/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/memgpt_classic/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=(
        'matched execution still requires an exact immutable MemoryArena dataset revision and deployment-bound benchmark environments',
    ),
    evidence_refs=(),
    scientific_tests=(
        'tests/test_scientific_memgpt_classic_fidelity_v1.py',
        'tests/test_scientific_memgpt_classic_method_program_v1.py',
        'tests/test_scientific_memgpt_memoryarena_protocol_v1.py',
    ),
)

__all__ = ["REPRODUCTION"]
