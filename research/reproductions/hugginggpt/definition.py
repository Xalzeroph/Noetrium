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
    ReproductionMethodConfigurerBinding,
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
    method_configurer=ReproductionMethodConfigurerBinding(
        qualname="build_hugginggpt_method_program",
        unresolved_parameters=("expert_capability_ids",),
    ),
    primary_executable="research/reproductions/hugginggpt/program.py",
    reported_results=(
        ReportedResult(
            claim_id="hugginggpt_gpt35_task_planning_passing",
            metric_id="human_evaluation_percent",
            value=91.22,
            qualifiers={
                "stage": "task-planning",
                "measure": "passing-rate",
                "model": "GPT-3.5",
                "request_count": 130,
                "source": "NeurIPS 2023 Table 8",
            },
        ),
        ReportedResult(
            claim_id="hugginggpt_gpt35_task_planning_rationality",
            metric_id="human_evaluation_percent",
            value=78.47,
            qualifiers={
                "stage": "task-planning",
                "measure": "rationality",
                "model": "GPT-3.5",
                "request_count": 130,
                "source": "NeurIPS 2023 Table 8",
            },
        ),
        ReportedResult(
            claim_id="hugginggpt_gpt35_model_selection_passing",
            metric_id="human_evaluation_percent",
            value=93.89,
            qualifiers={
                "stage": "model-selection",
                "measure": "passing-rate",
                "model": "GPT-3.5",
                "request_count": 130,
                "source": "NeurIPS 2023 Table 8",
            },
        ),
        ReportedResult(
            claim_id="hugginggpt_gpt35_model_selection_rationality",
            metric_id="human_evaluation_percent",
            value=84.29,
            qualifiers={
                "stage": "model-selection",
                "measure": "rationality",
                "model": "GPT-3.5",
                "request_count": 130,
                "source": "NeurIPS 2023 Table 8",
            },
        ),
        ReportedResult(
            claim_id="hugginggpt_gpt35_response_success",
            metric_id="human_evaluation_percent",
            value=63.08,
            qualifiers={
                "stage": "response",
                "measure": "success-rate",
                "model": "GPT-3.5",
                "request_count": 130,
                "source": "NeurIPS 2023 Table 8",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="alpaca13b_human_eval",
            description=(
                "Alpaca-13B human-evaluation baseline reported in HuggingGPT "
                "Table 8."
            ),
            qualifiers={
                "task_planning_passing_percent": 51.04,
                "task_planning_rationality_percent": 32.17,
                "response_success_percent": 6.92,
            },
        ),
        ReferenceBaseline(
            baseline_id="vicuna13b_human_eval",
            description=(
                "Vicuna-13B human-evaluation baseline reported in HuggingGPT "
                "Table 8."
            ),
            qualifiers={
                "task_planning_passing_percent": 79.41,
                "task_planning_rationality_percent": 58.41,
                "response_success_percent": 15.64,
            },
        ),
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
    scientific_tests=('tests/test_scientific_hugginggpt_v1.py',),
)

__all__ = ["REPRODUCTION"]
