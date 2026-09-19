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
    package='toolllm_toolbench',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='toolllm',
        title='ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs',
        paper_uri='https://proceedings.iclr.cc/paper_files/paper/2024/hash/28e50ee5b72e90b50e7196fde8ea260e-Abstract-Conference.html',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('tool-use', 'training'),
        families=('tool_use', 'retrieval', 'search', 'api_agent'),
        priority=1,
        benchmark_ids=('toolbench',),
        platform_pressure=('participant/capability', 'data/projection', 'data/query', 'model/request', 'execution', 'observability/telemetry'),
        method_owned=('API Retriever task-conditioned top-k policy', 'function-schema materialization and Finish injection semantics', 'DFSDT tool-search policy'),
        platform_owned=('capability descriptor authority', 'semantic projection and query', 'capability invocation and effect evidence', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/toolllm_toolbench/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/toolllm_toolbench/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/toolllm_toolbench/study.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/toolllm_toolbench/search.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/toolllm_toolbench/selection.py',
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
    scientific_tests=('tests/test_scientific_toolllm_dfsdt_v1.py', 'tests/test_scientific_toolllm_toolbench_v1.py', 'tests/test_scientific_toolllm_method_program_v1.py', 'tests/test_scientific_toolbench_cut_v1.py', 'tests/test_scientific_toolllm_study_v1.py'),
)

__all__ = ["REPRODUCTION"]
