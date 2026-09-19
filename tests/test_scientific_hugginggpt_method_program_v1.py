from __future__ import annotations

from hashlib import sha256

from research.benchmarks.hugginggpt_paper_tasks import (
    HUGGINGGPT_BENCHMARK_ID,
    HuggingGPTPaperTaskRecord,
    build_hugginggpt_paper_task_set,
)
from research.reproductions.hugginggpt.program import (
    build_hugginggpt_method_program,
)
from research.reproductions.hugginggpt.study import build_hugginggpt_study


def _benchmark():
    rows = (
        HuggingGPTPaperTaskRecord(
            "hugginggpt:paper:001",
            "Describe the image and produce a spoken summary.",
            sha256(b"task-001").hexdigest(),
            ("text", "image", "audio"),
        ),
    )
    return build_hugginggpt_paper_task_set(
        rows,
        dataset_content_sha256=sha256(b"hugginggpt-paper-cut").hexdigest(),
    )


def test_hugginggpt_program_freezes_expert_capability_closure() -> None:
    first = build_hugginggpt_method_program(
        ("expert.image-caption", "expert.text-to-speech"),
    )
    second = build_hugginggpt_method_program(
        ("expert.image-caption", "expert.text-generation"),
    )
    assert first.program_digest != second.program_digest
    assert first.required_capabilities == (
        "expert.image-caption",
        "expert.text-to-speech",
    )


def test_hugginggpt_paper_cut_and_study_bind_four_stage_protocol() -> None:
    benchmark = _benchmark()
    assert benchmark.benchmark_id == HUGGINGGPT_BENCHMARK_ID
    study = build_hugginggpt_study(
        benchmark,
        split_id="paper-era",
        expert_capability_ids=(
            "expert.image-caption",
            "expert.text-to-speech",
        ),
    )
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.trial_protocol_identity.protocol_id == (
        "hugginggpt.neurips2023.paper-tasks.v1"
    )
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.definitions
    ) == (
        "task_success",
        "subtask_count",
        "expert_call_count",
        "model_call_count",
    )
