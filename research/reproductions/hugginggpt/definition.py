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
    package='hugginggpt',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='hugginggpt',
        title='HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in Hugging Face',
        paper_uri='https://proceedings.neurips.cc/paper_files/paper/2023/hash/77c33e6a367922d003ff102ffb92b658-Abstract-Conference.html',
        year=2023,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('multimodal', 'tool-use', 'planning-search', 'runtime-systems'),
        families=('multimodal', 'model_orchestration', 'planning', 'tool_use'),
        priority=1,
        benchmark_ids=('hugginggpt-paper-tasks',),
        platform_pressure=('participant/method', 'model/request', 'participant/capability', 'execution', 'artifact/lineage'),
        method_owned=('task decomposition policy', 'expert-model selection policy', 'dependency-aware execution policy', 'response aggregation policy'),
        platform_owned=('method graph execution', 'model and capability invocation', 'artifact references', 'parallel scheduling', 'evidence and telemetry'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/hugginggpt/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/hugginggpt/task_graph.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/hugginggpt/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/hugginggpt/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The paper implementation may execute multiple dependency-ready "
                "subtasks concurrently. The current MethodProgram preserves the "
                "same dependency-ready set and deterministic task identities but "
                "dispatches ready subtasks one at a time until the generic Method "
                "execution surface gains batch-ready-set authoring."
            ),
        ),
    ),
    blockers=(
        "matched NeurIPS results require the exact paper-era ChatGPT service revision and expert-model inventory/availability cut",
        "the released qualitative task examples must be materialized as an immutable task dataset before claim-ready execution",
        "physical concurrent dispatch of one dependency-ready set is not yet expressed by MethodProgram",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_hugginggpt_v1.py', 'tests/test_scientific_hugginggpt_method_program_v1.py'),
)

__all__ = ["REPRODUCTION"]
