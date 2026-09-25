from __future__ import annotations

from research.benchmarks.robocodegen_37 import (
    ROBOCODEGEN_ALL_SPLIT,
    ROBOCODEGEN_NOTEBOOK_BLOB_SHA,
    ROBOCODEGEN_TASK_COUNT,
    ROBOCODEGEN_TASK_SIGNATURES,
    build_robocodegen_37_cut,
)
from research.reproductions.code_as_policies.study import (
    build_code_as_policies_icra2023_robocodegen_study,
    code_as_policies_icra2023_robocodegen_protocol,
)


def test_robocodegen_cut_freezes_all_official_notebook_tasks() -> None:
    benchmark = build_robocodegen_37_cut()
    selected = benchmark.selected_tasks(ROBOCODEGEN_ALL_SPLIT)
    assert len(selected) == ROBOCODEGEN_TASK_COUNT == 37
    assert len(ROBOCODEGEN_TASK_SIGNATURES) == 37
    assert len({name for name, _ in ROBOCODEGEN_TASK_SIGNATURES}) == 37
    assert ROBOCODEGEN_NOTEBOOK_BLOB_SHA == (
        "a8a33ad43758be446e033a3cb65ace4a2cb031f3"
    )
    assert tuple(row.task_id for row in selected) == tuple(
        sorted(row.task_id for row in selected)
    )


def test_code_as_policies_robocodegen_study_binds_hierarchical_treatment() -> None:
    benchmark = build_robocodegen_37_cut()
    protocol = code_as_policies_icra2023_robocodegen_protocol(benchmark)
    study = build_code_as_policies_icra2023_robocodegen_study(benchmark)

    assert protocol.protocol_id == (
        "code-as-policies.icra2023.robocodegen-37.v1"
    )
    assert study.trial_protocol_identity == protocol
    assert {
        row.measurement_id for row in study.measurement_protocol.definitions
    } == {"generated_helper_count", "task_success"}
