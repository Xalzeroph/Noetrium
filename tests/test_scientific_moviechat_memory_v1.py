from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.evidence.artifact.content.api import TensorContentRef
from noetrium_platform.evidence.artifact.content.providers import (
    CanonicalJsonTensorContentStore,
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from research.benchmarks.moviechat_1k import (
    MOVIECHAT_1K_BENCHMARK_ID,
    MOVIECHAT_1K_TEST_SPLIT,
    MovieChatQuestion,
    MovieChatVideoRecord,
)
from research.reproductions.moviechat_memory.benchmark import (
    build_moviechat_cvpr2024_test_cut,
)
from research.reproductions.moviechat_memory.study import (
    build_moviechat_cvpr2024_study,
    moviechat_cvpr2024_trial_protocol,
)
from research.reproductions.moviechat_memory.memory import (
    MOVIECHAT_MEMORY_PROGRAM,
    MovieChatMemoryBinding,
    consolidate_direct_long_memory,
    consolidate_short_memory,
    moviechat_memory_host,
    moviechat_memory_initial_data,
)


_FRAGMENT_SCHEMA = "moviechat.fragment-frame-embeddings.tensor.v1"
_FRAME_SCHEMA = "moviechat.frame-embedding.tensor.v1"


def _event(kind: str, payload: dict) -> dict:
    return {
        "event": {
            "kind": kind,
            "payload": payload,
            "source": "test",
        }
    }


def _store(root: Path) -> CanonicalJsonTensorContentStore:
    blob = DirectoryArtifactBlobStore(root / "blob")
    return CanonicalJsonTensorContentStore(
        blob,
        blob_store_identity_digest=canonical_digest({
            "provider": "test-directory-artifact-blob-store",
            "root": str((root / "blob").resolve()),
        }),
    )


def _sequence_ref(
    store: CanonicalJsonTensorContentStore,
    frames,
) -> dict:
    return store.put(
        frames,
        schema_id=_FRAGMENT_SCHEMA,
    ).payload()


def _frame_ref(
    store: CanonicalJsonTensorContentStore,
    frame,
) -> dict:
    return store.put(
        frame,
        schema_id=_FRAME_SCHEMA,
    ).payload()


def test_moviechat_short_and_long_paths_select_different_pairs() -> None:
    frames = (
        ((1.0, 0.0),),
        ((0.9, 0.1),),
        ((-1.0, 0.0),),
    )

    short, short_receipts = consolidate_short_memory(
        frames,
        target_length=2,
    )
    direct_long, long_receipts = consolidate_direct_long_memory(
        frames,
        target_length=2,
    )

    assert short_receipts[0].pair_index == 0
    assert short_receipts[0].selection_metric == (
        "mean_pairwise_token_dot_product"
    )
    assert short[0][0] == pytest.approx((0.95, 0.05))

    # The released source uses scipy cosine *distance* and max().
    assert long_receipts[0].pair_index == 1
    assert long_receipts[0].selection_metric == "scipy_cosine_distance"
    assert direct_long[1][0] == pytest.approx((-0.05, 0.05))


def test_moviechat_fragment_memory_preserves_uncompressed_breakpoint_window(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    journal = InMemoryMachineJournal()
    binding = MovieChatMemoryBinding(tensor_store=store)
    host = moviechat_memory_host(journal=journal)
    machine_id = "memory:moviechat:test"
    identity = {
        "memory_id": "moviechat:test",
        "program_digest": MOVIECHAT_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }
    initial = moviechat_memory_initial_data()

    frames = (
        ((1.0, 0.0), (1.0, 0.0)),
        ((0.9, 0.1), (0.9, 0.1)),
        ((0.0, 1.0), (0.0, 1.0)),
        ((-1.0, 0.0), (-1.0, 0.0)),
    )
    committed = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "moviechat.fragment.commit",
            {"frames_ref": _sequence_ref(store, frames)},
        ),
        command_id_prefix="moviechat:test",
    )

    assert committed.status is MachineStatus.RUNNABLE
    assert committed.data["short_memory_ref"] is None
    temp_ref = TensorContentRef.from_payload(
        committed.data["temp_short_memory_ref"]
    )
    long_ref = TensorContentRef.from_payload(
        committed.data["long_memory_ref"]
    )
    assert len(store.get(temp_ref)) == 4
    assert len(store.get(long_ref)) == 2
    assert committed.previous_value["temp_short_length"] == 4
    assert committed.previous_value["consolidated_short_length"] == 2
    assert len(committed.previous_value["short_merge_receipts"]) == 2

    global_read = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "moviechat.memory.read",
            {"mode": "global"},
        ),
        command_id_prefix="moviechat:test",
    )
    assert global_read.previous_value["frame_count"] == 2
    global_ref = TensorContentRef.from_payload(
        global_read.previous_value["readout_ref"]
    )
    assert store.get(global_ref) == store.get(long_ref)

    breakpoint = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "moviechat.memory.read",
            {
                "mode": "breakpoint",
                "current_frame_ref": _frame_ref(
                    store,
                    (
                        (0.5, 0.5),
                        (0.5, 0.5),
                    ),
                ),
            },
        ),
        command_id_prefix="moviechat:test",
    )
    assert breakpoint.previous_value["frame_count"] == 7
    assert breakpoint.previous_value["evicted_temp_short_count"] == 0
    assert breakpoint.previous_value["evicted_long_count"] == 0
    assert (
        breakpoint.previous_value["source_current_frame_omitted"]
        is False
    )
    breakpoint_ref = TensorContentRef.from_payload(
        breakpoint.previous_value["readout_ref"]
    )
    assert len(store.get(breakpoint_ref)) == 7

    # Journaled Machine state contains refs/digests, not embedding arrays.
    assert '"frames"' not in str(breakpoint.data)
    assert len(journal.commits(machine_id)) == breakpoint.revision


def test_moviechat_fragment_fifo_retains_only_latest_short_window(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    journal = InMemoryMachineJournal()
    binding = MovieChatMemoryBinding(tensor_store=store)
    host = moviechat_memory_host(journal=journal)
    machine_id = "memory:moviechat:fifo"
    identity = {
        "memory_id": "moviechat:fifo",
        "program_digest": MOVIECHAT_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }
    initial = moviechat_memory_initial_data()

    frames = tuple(
        ((float(index + 1), 1.0),)
        for index in range(20)
    )
    committed = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "moviechat.fragment.commit",
            {"frames_ref": _sequence_ref(store, frames)},
        ),
        command_id_prefix="moviechat:fifo",
    )

    temp_ref = TensorContentRef.from_payload(
        committed.data["temp_short_memory_ref"]
    )
    temp = store.get(temp_ref)
    assert len(temp) == 18
    assert temp[0] == [[3.0, 1.0]]
    assert temp[-1] == [[20.0, 1.0]]
    long_ref = TensorContentRef.from_payload(
        committed.data["long_memory_ref"]
    )
    assert len(store.get(long_ref)) == 2


def test_moviechat_reset_clears_both_memory_levels(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    journal = InMemoryMachineJournal()
    binding = MovieChatMemoryBinding(tensor_store=store)
    host = moviechat_memory_host(journal=journal)
    machine_id = "memory:moviechat:reset"
    identity = {
        "memory_id": "moviechat:reset",
        "program_digest": MOVIECHAT_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }
    initial = moviechat_memory_initial_data()

    host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "moviechat.fragment.commit",
            {
                "frames_ref": _sequence_ref(
                    store,
                    (
                        ((1.0, 0.0),),
                        ((0.0, 1.0),),
                    ),
                ),
            },
        ),
        command_id_prefix="moviechat:reset",
    )
    reset = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "moviechat.memory.reset",
            {},
        ),
        command_id_prefix="moviechat:reset",
    )

    assert reset.previous_value["cleared"] is True
    assert reset.data["short_memory_ref"] is None
    assert reset.data["temp_short_memory_ref"] is None
    assert reset.data["long_memory_ref"] is None



def _moviechat_video_record(index: int) -> MovieChatVideoRecord:
    global_questions = tuple(
        MovieChatQuestion(
            question=f"global question {index}-{qa_index}",
            answer=f"global answer {index}-{qa_index}",
        )
        for qa_index in range(3)
    )
    breakpoint_questions = tuple(
        MovieChatQuestion(
            question=f"breakpoint question {index}-{qa_index}",
            answer=f"breakpoint answer {index}-{qa_index}",
            breakpoint_frame=10 * (qa_index + 1),
        )
        for qa_index in range(10)
    )
    return MovieChatVideoRecord(
        video_name=f"movie_{index:04d}.mp4",
        fps=25.0,
        num_frames=1000,
        global_questions=global_questions,
        breakpoint_questions=breakpoint_questions,
        content_digest=canonical_digest({
            "video": index,
            "global": tuple(
                row.question_digest for row in global_questions
            ),
            "breakpoint": tuple(
                row.question_digest for row in breakpoint_questions
            ),
        }),
    )


def test_moviechat_1k_benchmark_preserves_per_video_qa_bundle() -> None:
    dataset_digest = canonical_digest({
        "dataset": "moviechat-1k-test-fixture",
    })
    benchmark = build_moviechat_cvpr2024_test_cut(
        tuple(_moviechat_video_record(index) for index in range(1000)),
        dataset_content_sha256=dataset_digest,
    )

    assert benchmark.benchmark_id == MOVIECHAT_1K_BENCHMARK_ID
    tasks = benchmark.selected_tasks(MOVIECHAT_1K_TEST_SPLIT)
    assert len(tasks) == 1000
    assert all(
        "global-qa-count:3" in task.lineage_refs
        and "breakpoint-qa-count:10" in task.lineage_refs
        for task in tasks
    )
    assert all(
        "global-mode:shared-video-memory" in task.lineage_refs
        and "breakpoint-mode:reset-per-question" in task.lineage_refs
        for task in tasks
    )


def test_moviechat_study_binds_memory_benchmark_and_paper_evaluator() -> None:
    dataset_digest = canonical_digest({
        "dataset": "moviechat-1k-study-fixture",
    })
    benchmark = build_moviechat_cvpr2024_test_cut(
        tuple(_moviechat_video_record(index) for index in range(1000)),
        dataset_content_sha256=dataset_digest,
    )

    protocol = moviechat_cvpr2024_trial_protocol(benchmark)
    definition = build_moviechat_cvpr2024_study(benchmark)

    assert protocol.protocol_id == "moviechat.cvpr2024.moviechat-1k.v1"
    assert definition.benchmark_split_id == MOVIECHAT_1K_TEST_SPLIT
    assert (
        definition.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    measurement_names = {
        measurement.measurement_id
        for measurement in definition.measurement_protocol.definitions
    }
    assert {
        "global_accuracy",
        "breakpoint_accuracy",
        "global_semantic_score",
        "breakpoint_semantic_score",
        "peak_long_memory_length",
    }.issubset(measurement_names)
