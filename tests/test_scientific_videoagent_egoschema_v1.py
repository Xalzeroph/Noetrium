from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.reproduction import ReproductionLifecycle
from research.benchmarks.egoschema import (
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
    EgoSchemaTaskRecord,
)
from research.reproductions.videoagent_memory import (
    REPRODUCTION,
    VIDEOAGENT_MEMORY_PROGRAM,
    VIDEOAGENT_METHOD_PROGRAM,
    build_videoagent_egoschema_public_cut,
    build_videoagent_egoschema_public_study,
    videoagent_egoschema_trial_protocol,
)


def _records() -> tuple[EgoSchemaTaskRecord, ...]:
    return tuple(
        EgoSchemaTaskRecord(
            q_uid=f"q-{index:04d}",
            question=f"What happens in video {index}?",
            options=(
                "option a",
                "option b",
                "option c",
                "option d",
                "option e",
            ),
            video_content_sha256=canonical_digest({
                "video": index,
            }),
            answer_index=index % 5,
        )
        for index in range(EGOSCHEMA_PUBLIC_COUNT)
    )


def test_videoagent_public_egoschema_cut_is_offline_verifiable_and_study_bound() -> None:
    benchmark = build_videoagent_egoschema_public_cut(
        _records(),
        questions_content_sha256=canonical_digest({
            "fixture": "egoschema-questions"
        }),
        public_answers_content_sha256=canonical_digest({
            "fixture": "egoschema-public-answers"
        }),
    )

    selected = benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)
    assert len(selected) == 500
    assert all(
        task.package is not None
        and task.package.verifier_requirement_id
        == "benchmark.egoschema.public-answer"
        for task in selected
    )

    protocol = videoagent_egoschema_trial_protocol(
        benchmark,
        split_id=EGOSCHEMA_PUBLIC_SPLIT,
    )
    study = build_videoagent_egoschema_public_study(benchmark)

    assert protocol.protocol_id == (
        "videoagent.eccv2024.egoschema.public-500.v1"
    )
    assert len(protocol.protocol_digest) == 64
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == EGOSCHEMA_PUBLIC_SPLIT
    assert VIDEOAGENT_METHOD_PROGRAM.program_digest
    assert VIDEOAGENT_MEMORY_PROGRAM.program_digest


def test_videoagent_reproduction_contract_is_protocol_bound_not_numerically_matched() -> None:
    assert REPRODUCTION.lifecycle.value == ReproductionLifecycle.PROTOCOL_BOUND.value
    assert REPRODUCTION.identity.method_id == "videoagent-memory"
    assert REPRODUCTION.catalog.benchmark_ids == ("egoschema",)
    assert {
        asset.kind.value for asset in REPRODUCTION.assets
    } >= {
        "fidelity",
        "research_program",
        "method_program",
        "benchmark",
        "study",
    }
    assert any(
        "GPT-4" in blocker for blocker in REPRODUCTION.blockers
    )
    assert any(
        "5031" in blocker for blocker in REPRODUCTION.blockers
    )
