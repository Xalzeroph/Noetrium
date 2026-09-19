from __future__ import annotations

from pathlib import Path

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
from research.benchmarks.lvu import (
    LVU_BENCHMARK_ID,
    LVUVideoRecord,
    MA_LMM_LVU_PROTOCOL,
    lvu_window_starts,
)
from research.reproductions.ma_lmm_memory.benchmark import (
    MA_LMM_LVU_TEST_SPLIT,
    build_ma_lmm_lvu_cut,
)
from research.reproductions.ma_lmm_memory.study import (
    build_ma_lmm_lvu_study,
    ma_lmm_lvu_trial_protocol,
)
from research.reproductions.ma_lmm_memory.memory import (
    MA_LMM_MEMORY_PROGRAM,
    MALMMMemoryBinding,
    compress_memory_bank,
    ma_lmm_memory_host,
    ma_lmm_memory_initial_data,
)


_FRAME_SCHEMA = "ma-lmm.frame-embedding.tensor.v1"


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


def _frame_ref(
    store: CanonicalJsonTensorContentStore,
    frame,
) -> dict:
    return store.put(frame, schema_id=_FRAME_SCHEMA).payload()


def test_ma_lmm_compression_selects_adjacent_pair_per_token() -> None:
    frames = (
        (
            (1.0, 0.0),
            (1.0, 0.0),
        ),
        (
            (1.0, 0.0),
            (0.0, 1.0),
        ),
        (
            (0.0, 1.0),
            (0.0, 1.0),
        ),
    )
    sizes = (
        (1, 1),
        (1, 1),
        (1, 1),
    )

    compressed, compressed_sizes, receipt = compress_memory_bank(
        frames,
        sizes,
    )

    assert receipt.merge_indices == (0, 1)
    assert receipt.before_length == 3
    assert receipt.after_length == 2
    assert compressed == (
        (
            (1.0, 0.0),
            (1.0, 0.0),
        ),
        (
            (0.0, 1.0),
            (0.0, 1.0),
        ),
    )
    assert compressed_sizes == (
        (2, 1),
        (1, 2),
    )


def test_ma_lmm_compression_uses_accumulated_frame_weights() -> None:
    frames = (
        ((1.0, 0.0),),
        ((0.0, 1.0),),
        ((0.0, 1.0),),
    )
    sizes = (
        (3,),
        (2,),
        (1,),
    )

    compressed, compressed_sizes, receipt = compress_memory_bank(
        frames,
        sizes,
    )

    assert receipt.merge_indices == (1,)
    assert compressed_sizes == ((3,), (3,))
    assert compressed[0][0] == (1.0, 0.0)
    assert compressed[1][0] == (0.0, 1.0)


def test_ma_lmm_memory_machine_streams_refs_compresses_and_clears(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    journal = InMemoryMachineJournal()
    binding = MALMMMemoryBinding(tensor_store=store)
    host = ma_lmm_memory_host(journal=journal)
    machine_id = "memory:ma-lmm:test"
    identity = {
        "memory_id": "ma-lmm:test",
        "program_digest": MA_LMM_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }
    initial = ma_lmm_memory_initial_data(
        memory_bank_length=2,
        num_frames=4,
    )

    frames = (
        ((1.0, 0.0), (1.0, 0.0)),
        ((1.0, 0.0), (0.0, 1.0)),
        ((0.0, 1.0), (0.0, 1.0)),
        ((1.0, 1.0), (1.0, 1.0)),
    )

    first = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "ma_lmm.memory.append",
            {
                "bank_id": "query.layer.0",
                "bank_kind": "query",
                "frame_ref": _frame_ref(store, frames[0]),
            },
        ),
        command_id_prefix="ma-lmm:test",
    )
    assert first.status is MachineStatus.RUNNABLE
    assert first.previous_value["active_length"] == 1
    assert first.previous_value["compression_receipt"] is None
    first_ref = TensorContentRef.from_payload(
        first.previous_value["memory_ref"]
    )
    assert tuple(tuple(row) for row in store.get(first_ref)[0]) == frames[0]

    second = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "ma_lmm.memory.append",
            {
                "bank_id": "query.layer.0",
                "bank_kind": "query",
                "frame_ref": _frame_ref(store, frames[1]),
            },
        ),
        command_id_prefix="ma-lmm:test",
    )
    assert second.previous_value["active_length"] == 2

    third = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "ma_lmm.memory.append",
            {
                "bank_id": "query.layer.0",
                "bank_kind": "query",
                "frame_ref": _frame_ref(store, frames[2]),
            },
        ),
        command_id_prefix="ma-lmm:test",
    )
    assert third.previous_value["active_length"] == 2
    assert tuple(third.previous_value["compression_receipt"]["merge_indices"]) == (
        0,
        1,
    )

    read = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "ma_lmm.memory.read",
            {"bank_id": "query.layer.0"},
        ),
        command_id_prefix="ma-lmm:test",
    )
    assert read.previous_value["active"] is True
    assert read.previous_value["attention_role"] == "prepend_key_value"
    read_ref = TensorContentRef.from_payload(
        read.previous_value["memory_ref"]
    )
    read_bank = store.get(read_ref)
    assert len(read_bank) == 2
    assert len(read_bank[0]) == 2

    final = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "ma_lmm.memory.append",
            {
                "bank_id": "query.layer.0",
                "bank_kind": "query",
                "frame_ref": _frame_ref(store, frames[3]),
                "final": True,
            },
        ),
        command_id_prefix="ma-lmm:test",
    )
    assert final.previous_value["active"] is False
    assert final.previous_value["seen_frames"] == 4
    released_ref = TensorContentRef.from_payload(
        final.previous_value["memory_ref"]
    )
    released_sizes_ref = TensorContentRef.from_payload(
        final.previous_value["compression_sizes_ref"]
    )
    released = store.get(released_ref)
    released_sizes = store.get(released_sizes_ref)
    assert len(released) == 3
    assert len(released_sizes) == 3
    assert tuple(final.data["banks"]) == ()

    # The Machine state carries immutable content refs, not raw embeddings.
    assert "frames" not in str(final.data)
    assert len(journal.commits(machine_id)) == final.revision



def _lvu_record(
    split_id: str,
    video_id: str,
    *,
    duration_seconds: int,
) -> LVUVideoRecord:
    annotations = tuple(
        (task, f"{task}-label")
        for task in MA_LMM_LVU_PROTOCOL.task_ids
    )
    answers = tuple(
        (task, "(a)")
        for task in MA_LMM_LVU_PROTOCOL.task_ids
    )
    return LVUVideoRecord(
        split_id=split_id,
        video_id=video_id,
        duration_seconds=duration_seconds,
        num_frames=duration_seconds * 10,
        annotations=annotations,
        answer_codes=answers,
        content_digest=canonical_digest({
            "split": split_id,
            "video": video_id,
            "duration_seconds": duration_seconds,
            "annotations": annotations,
        }),
    )


def test_ma_lmm_lvu_window_policy_matches_released_dataset_loop() -> None:
    assert lvu_window_starts(80, MA_LMM_LVU_PROTOCOL) == (0,)
    assert lvu_window_starts(100, MA_LMM_LVU_PROTOCOL) == (0,)
    assert lvu_window_starts(180, MA_LMM_LVU_PROTOCOL) == (
        0,
        20,
        40,
        60,
        80,
    )


def test_ma_lmm_lvu_benchmark_and_study_bind_all_seven_tasks() -> None:
    dataset_digest = canonical_digest({
        "dataset": "lvu-1.0-test-fixture",
    })
    benchmark = build_ma_lmm_lvu_cut(
        (
            _lvu_record(
                "train",
                "movie-train",
                duration_seconds=100,
            ),
            _lvu_record(
                "test",
                "movie-test",
                duration_seconds=180,
            ),
        ),
        dataset_content_sha256=dataset_digest,
    )

    assert benchmark.benchmark_id == LVU_BENCHMARK_ID
    test_tasks = benchmark.selected_tasks(MA_LMM_LVU_TEST_SPLIT)
    assert len(test_tasks) == 35
    assert len(benchmark.selected_tasks("test:relationship")) == 5
    assert {
        task.family for task in test_tasks
    } == {
        f"lvu_{task}"
        for task in MA_LMM_LVU_PROTOCOL.task_ids
    }

    protocol = ma_lmm_lvu_trial_protocol(benchmark)
    definition = build_ma_lmm_lvu_study(benchmark)

    assert protocol.protocol_id == "ma-lmm.cvpr2024.lvu.v1"
    assert definition.benchmark_split_id == MA_LMM_LVU_TEST_SPLIT
    assert (
        definition.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    assert len(protocol.configuration_digest) == 64
