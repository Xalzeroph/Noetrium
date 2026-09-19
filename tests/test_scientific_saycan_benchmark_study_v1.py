from __future__ import annotations

from research.benchmarks.saycan_101 import (
    SAYCAN_ALL_SPLIT,
    SAYCAN_DATA_COMMIT,
    SAYCAN_INITIAL_CONDITIONS_BLOB_SHA,
    SAYCAN_PLAN_REFERENCE_BLOB_SHA,
    SAYCAN_TASK_COUNT,
    SayCanTaskRecord,
    bind_saycan_v0,
    parse_saycan_initial_conditions_tsv,
)
from research.reproductions.saycan import (
    SayCanEvaluationScene,
    build_saycan_101_benchmark,
    build_saycan_corl2022_study,
    saycan_corl2022_trial_protocol,
)


_FAMILY_COUNTS = (
    ('Context / Disturbances = No "How would you"', 15),
    ("Multiple", 15),
    ("Abstract Task Specification: Verb synonyms", 15),
    ("Structured Language", 1),
    ("Mirror Verb synonyms", 14),
    ("Abstract Task Specification: Noun synonyms", 15),
    ("Embodiment", 11),
    ("Abstract Task Specification: Single", 15),
)


def _records() -> tuple[SayCanTaskRecord, ...]:
    rows = []
    index = 1
    for family, count in _FAMILY_COUNTS:
        for offset in range(count):
            rows.append(
                SayCanTaskRecord(
                    index=index,
                    family=family,
                    query=f"{family} task {offset + 1}",
                    robot_start_state="with operator",
                    environment_start_state=f"fixture state {index}",
                )
            )
            index += 1
    assert index == SAYCAN_TASK_COUNT + 1
    return tuple(rows)


def _tsv() -> str:
    lines = [
        "Task Family\tQuery\tRobot Start State\tEnv Start State "
    ]
    index = 1
    for family, count in _FAMILY_COUNTS:
        for offset in range(count):
            family_cell = family if offset == 0 else ""
            lines.append(
                "\t".join((
                    family_cell,
                    f"{family} task {offset + 1}",
                    "with operator",
                    f"fixture state {index}",
                ))
            )
            index += 1
    return "\r\n".join(lines) + "\r\n"


def test_saycan_official_v0_authority_freezes_101_task_source() -> None:
    assert SAYCAN_DATA_COMMIT == (
        "69886495c40568ed782833c4440c831cf7bfda7a"
    )
    assert SAYCAN_INITIAL_CONDITIONS_BLOB_SHA == (
        "0db34cc71e82e875d8549a4918d3121a9a14399d"
    )
    assert SAYCAN_PLAN_REFERENCE_BLOB_SHA == (
        "1c9ae055d28e98fc005378f67ead432f6e16fc7e"
    )

    parsed = parse_saycan_initial_conditions_tsv(_tsv())
    assert len(parsed) == SAYCAN_TASK_COUNT
    counts = {}
    for row in parsed:
        counts[row.family] = counts.get(row.family, 0) + 1
    assert tuple((family, counts[family]) for family, _ in _FAMILY_COUNTS) == (
        _FAMILY_COUNTS
    )


def test_saycan_benchmark_is_human_majority_not_reference_plan_exact_match() -> None:
    resolution = bind_saycan_v0(_records())
    benchmark = build_saycan_101_benchmark(_records())
    assert resolution.task_set.cut_digest == benchmark.cut_digest
    selected = benchmark.selected_tasks(SAYCAN_ALL_SPLIT)
    assert len(selected) == 101
    assert all(
        task.package is not None
        and task.package.verifier_requirement_id
        == "benchmark.saycan.human-majority"
        for task in selected
    )
    assert all(
        any(
            row == "plan-verifier:human-majority-2-of-3"
            for row in task.lineage_refs
        )
        for task in selected
    )
    assert all(
        any(
            row == "execution-verifier:human-majority-2-of-3"
            for row in task.lineage_refs
        )
        for task in selected
    )


def test_saycan_study_binds_101_tasks_and_scene_specific_protocol() -> None:
    benchmark = build_saycan_101_benchmark(_records())
    mock_protocol = saycan_corl2022_trial_protocol(
        benchmark,
        scene=SayCanEvaluationScene.MOCK_KITCHEN,
    )
    real_protocol = saycan_corl2022_trial_protocol(
        benchmark,
        scene=SayCanEvaluationScene.REAL_KITCHEN,
    )
    assert mock_protocol.protocol_id == (
        "saycan.corl2022.mock_kitchen.101.v1"
    )
    assert real_protocol.protocol_id == (
        "saycan.corl2022.real_kitchen.101.v1"
    )
    assert mock_protocol.configuration_digest != (
        real_protocol.configuration_digest
    )

    study = build_saycan_corl2022_study(
        benchmark,
        scene=SayCanEvaluationScene.MOCK_KITCHEN,
    )
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == SAYCAN_ALL_SPLIT
    assert (
        study.trial_protocol_identity.configuration_digest
        == mock_protocol.configuration_digest
    )
    names = {
        row.measurement_id
        for row in study.measurement_protocol.definitions
    }
    assert {
        "plan_success",
        "execution_success",
        "planning_calls",
        "executed_skill_count",
    } == names
