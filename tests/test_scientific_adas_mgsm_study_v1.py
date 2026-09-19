from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api.research_compiler import _assignments
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkAssignmentMode,
    BenchmarkTaskSet,
    StudyVariantSpec,
    TaskDefinition,
    TaskSetSplit,
    VariantKind,
)
from research.benchmarks.mgsm import (
    MGSM_ADAS_TEST_SPLIT,
    MGSM_ADAS_VALID_SPLIT,
    MGSM_BENCHMARK_ID,
)
from research.reproductions.adas_meta_agent_search.study import (
    adas_mgsm_search_trial_protocol,
    build_adas_mgsm_search_study,
)


def _benchmark() -> BenchmarkTaskSet:
    revision = "mgsm-test-cut-v1"
    test_ids = tuple(f"mgsm:test:{index:03d}" for index in range(800))
    valid_ids = tuple(f"mgsm:valid:{index:03d}" for index in range(128))
    all_ids = tuple(sorted((*test_ids, *valid_ids)))
    tasks = tuple(
        TaskDefinition(
            task_id,
            revision,
            "mgsm",
            "mgsm.multilingual-math-task.v1",
            canonical_digest({"task_id": task_id}),
        )
        for task_id in all_ids
    )
    return BenchmarkTaskSet(
        MGSM_BENCHMARK_ID,
        revision,
        canonical_digest({"mgsm": "frozen-cut"}),
        "mgsm.multilingual-math-task.v1",
        tasks,
        splits=(
            TaskSetSplit(MGSM_ADAS_TEST_SPLIT, test_ids),
            TaskSetSplit(MGSM_ADAS_VALID_SPLIT, valid_ids),
        ),
        selection_policy_digest=canonical_digest(
            {
                "shuffle_seed": 0,
                "valid": valid_ids,
                "test": test_ids,
            }
        ),
    )


def _variant() -> StudyVariantSpec:
    return StudyVariantSpec(
        "paper-era",
        VariantKind.CONTROL,
        "trial.method-program",
        canonical_digest({"treatment": "paper-era-mgsm-meta-agent-search"}),
    )


def test_adas_study_runs_one_outer_assignment_over_whole_validation_cut() -> None:
    benchmark = _benchmark()
    definition = build_adas_mgsm_search_study(benchmark)

    assert definition.benchmark_assignment_mode is BenchmarkAssignmentMode.CUT
    assert definition.benchmark_split_id == MGSM_ADAS_VALID_SPLIT
    assert len(definition.benchmark.selected_tasks(MGSM_ADAS_VALID_SPLIT)) == 128
    assert len(definition.benchmark.selected_tasks(MGSM_ADAS_TEST_SPLIT)) == 800

    assignments = _assignments(definition, (_variant(),))
    assert len(assignments) == 1
    assert assignments[0].task_id is None

    meta_search = next(
        row
        for row in definition.binding_requirements.participants
        if row.role == "meta_search"
    )
    assert meta_search.capability_requirement_ids == (
        "workbench.candidate-program.execute",
    )


def test_adas_trial_identity_binds_program_benchmark_and_no_test_search_leakage() -> None:
    benchmark = _benchmark()
    protocol = adas_mgsm_search_trial_protocol(benchmark)
    definition = build_adas_mgsm_search_study(benchmark)

    assert protocol.protocol_id == "adas.meta-agent-search.mgsm.validation.v1"
    assert (
        protocol.configuration_digest
        == definition.trial_protocol_identity.configuration_digest
    )
    assert len(protocol.configuration_digest) == 64
