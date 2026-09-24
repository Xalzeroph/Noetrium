from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.robocodegen_37 import (
    ROBOCODEGEN_ALL_SPLIT,
    ROBOCODEGEN_BENCHMARK_ID,
    ROBOCODEGEN_NOTEBOOK_BLOB_SHA,
    ROBOCODEGEN_PROTOCOL_DIGEST,
    ROBOCODEGEN_TASK_COUNT,
    ROBOCODEGEN_TESTS_PER_TASK,
)

from .program import CODE_AS_POLICIES_METHOD_PROGRAM
from .source import CODE_AS_POLICIES_AUDITED_COMMIT


def code_as_policies_icra2023_robocodegen_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != ROBOCODEGEN_BENCHMARK_ID:
        raise ValueError("Code as Policies study requires RoboCodeGen 37")
    selected = benchmark.selected_tasks(ROBOCODEGEN_ALL_SPLIT)
    if len(selected) != ROBOCODEGEN_TASK_COUNT:
        raise ValueError("Code as Policies study requires all 37 tasks")
    return ExperimentTrialProtocolIdentity(
        "code-as-policies.icra2023.robocodegen-37.v1",
        canonical_digest({
            "source_commit": CODE_AS_POLICIES_AUDITED_COMMIT,
            "notebook_blob_sha": ROBOCODEGEN_NOTEBOOK_BLOB_SHA,
            "method_program_digest": CODE_AS_POLICIES_METHOD_PROGRAM.program_digest,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_protocol_digest": ROBOCODEGEN_PROTOCOL_DIGEST,
            "benchmark_split_id": ROBOCODEGEN_ALL_SPLIT,
            "task_ids": tuple(row.task_id for row in selected),
            "tests_per_task": ROBOCODEGEN_TESTS_PER_TASK,
            "test_seed": "paper-notebook-unfixed",
            "model": "code-davinci-002",
            "generation": "hierarchical-code-gen",
            "prompt": "hierarchical",
            "temperature": 0.0,
            "max_tokens": 512,
        }),
    )


def build_code_as_policies_icra2023_robocodegen_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = code_as_policies_icra2023_robocodegen_protocol(benchmark)
    return Study(
        project_id="code-as-policies-icra-2023-reproduction",
        study_id="code-as-policies-icra-2023-robocodegen-37",
        benchmark=benchmark,
        benchmark_split_id=ROBOCODEGEN_ALL_SPLIT,
        method=StudyParticipant(
            role="hierarchical_language_model_program_generator",
            kind="method",
            implementation="code-as-policies",
            treatment="hierarchical-code-gen-hierarchical-prompt",
            capabilities=(
                "model.generate",
                "environment.software",
            ),
            configurations=(
                "code-as-policies.recursive-helper-synthesis",
                "code-as-policies.hierarchical-prompt",
                "code-as-policies.paper-era-codex",
            ),
        ),
        models={
            "synthesizer": StudyModel(
                "model.openai.code-davinci-002-paper-era",
                prompt="code-as-policies.robocodegen.hierarchical",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.ratio.v1",
                unit="ratio",
                semantic_kind="reference_function_equivalence",
                scale="binary",
                domain="robocodegen_37",
            ),
            MeasurementDefinition.scalar(
                "generated_helper_count",
                schema_id="noetrium.measurement.count.v1",
                unit="helper",
                semantic_kind="recursive_generated_helper_count",
                scale="count",
                domain="robocodegen_37",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-notebook-random-seed-unfixed",),
        limits=TrialBudget(
            "code-as-policies-robocodegen-37-budget",
            max_steps=256,
            max_turns=64,
            max_model_calls=256,
            max_working_seconds=600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=600.0,
    ).build()


__all__ = [
    "build_code_as_policies_icra2023_robocodegen_study",
    "code_as_policies_icra2023_robocodegen_protocol",
]
