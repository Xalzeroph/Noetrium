from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.egolifeqa import (
    EGOLIFEQA_BENCHMARK_ID,
    EgoLifeQATaskRecord,
)
from research.reproductions.worldmm_memory import (
    WORLDMM_MEMORY_PROGRAM,
    WORLDMM_METHOD_PROGRAM,
    build_worldmm_egolifeqa_study,
    build_worldmm_egolifeqa_subject_cut,
    worldmm_egolifeqa_trial_protocol,
)


def _records():
    return (
        EgoLifeQATaskRecord(
            subject_id="A1_JAKE",
            question_id="1",
            query_type="EntityLog",
            question="Who owns the blue bag?",
            choices=(
                ("A", "Maria"),
                ("B", "Alex"),
                ("C", "Luis"),
                ("D", "Sam"),
            ),
            answer_label="B",
            query_time=110300000,
            target_time_ranges=((110000000, 110000030),),
        ),
        EgoLifeQATaskRecord(
            subject_id="A1_JAKE",
            question_id="2",
            query_type="EventRecall",
            question="What happened after breakfast?",
            choices=(
                ("A", "Shopping"),
                ("B", "Sleeping"),
                ("C", "Cooking"),
                ("D", "Running"),
            ),
            answer_label="A",
            query_time=111200000,
            target_time_ranges=((110900000, 111000000),),
        ),
    )


def test_worldmm_binds_content_addressed_egolifeqa_study() -> None:
    source_digest = canonical_digest({
        "fixture": "egolifeqa-A1_JAKE",
        "revision": 1,
    })
    benchmark = build_worldmm_egolifeqa_subject_cut(
        _records(),
        question_file_content_sha256=source_digest,
        subject_id="A1_JAKE",
    )
    assert benchmark.benchmark_id == EGOLIFEQA_BENCHMARK_ID
    selected = benchmark.selected_tasks("subject:A1_JAKE")
    assert len(selected) == 2
    assert all(
        task.task_id.startswith("egolifeqa:A1_JAKE:")
        for task in selected
    )

    trial = worldmm_egolifeqa_trial_protocol(
        benchmark,
        subject_id="A1_JAKE",
    )
    assert trial.protocol_id == (
        "worldmm.cvpr2026.egolifeqa.A1_JAKE.v1"
    )

    study = build_worldmm_egolifeqa_study(
        benchmark,
        subject_id="A1_JAKE",
    )
    assert study.benchmark_split_id == "subject:A1_JAKE"
    assert study.method.implementation == "worldmm-memory"
    assert study.trial == trial
    assert WORLDMM_METHOD_PROGRAM.program_digest
    assert WORLDMM_MEMORY_PROGRAM.program_digest
    assert tuple(study.models) == ("responder", "retriever")
    assert tuple(
        measurement.name for measurement in study.measurements
    ) == (
        "multiple_choice_accuracy",
        "retrieval_rounds",
        "reasoning_errors",
        "retrieved_item_count",
    )
