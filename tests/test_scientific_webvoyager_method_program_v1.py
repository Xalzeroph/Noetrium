from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.webvoyager import (
    OfficialWebVoyagerTaskRecord,
    WEBVOYAGER_OFFICIAL_SPLIT,
    WEBVOYAGER_OFFICIAL_TASK_COUNT,
    build_official_webvoyager_task_set,
)
from research.reproductions.webvoyager.program import (
    WEBVOYAGER_METHOD_PROGRAM,
)
from research.reproductions.webvoyager.study import (
    WEBVOYAGER_ACL2024_TRIAL_PROTOCOL,
    build_webvoyager_official_study,
)


def _benchmark():
    rows = tuple(
        OfficialWebVoyagerTaskRecord(
            index=index,
            task_id=f"webvoyager:{index:03d}",
            website="example",
            question=f"task {index}",
            start_url="https://example.com",
            content_digest=canonical_digest({"index": index}),
        )
        for index in range(WEBVOYAGER_OFFICIAL_TASK_COUNT)
    )
    return build_official_webvoyager_task_set(
        rows,
        source_digest=canonical_digest({"source": "webvoyager-official"}),
    )


def test_webvoyager_method_program_preserves_released_loop_contract() -> None:
    assert WEBVOYAGER_METHOD_PROGRAM.configuration["max_iterations"] == 15
    assert WEBVOYAGER_METHOD_PROGRAM.configuration["max_attached_images"] == 3
    assert WEBVOYAGER_METHOD_PROGRAM.configuration["environment_action_capability"] == (
        "environment.act"
    )
    assert WEBVOYAGER_METHOD_PROGRAM.required_capabilities == ("environment.act",)


def test_webvoyager_official_study_binds_all_643_tasks() -> None:
    benchmark = _benchmark()
    study = build_webvoyager_official_study(benchmark)
    assert study.benchmark_split_id == WEBVOYAGER_OFFICIAL_SPLIT
    assert len(study.benchmark.selected_tasks(WEBVOYAGER_OFFICIAL_SPLIT)) == 643
    assert (
        study.trial_protocol_identity.protocol_id
        == WEBVOYAGER_ACL2024_TRIAL_PROTOCOL.protocol_id
    )
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.measurements
    ) == ("task_success", "step_count", "model_call_count")
