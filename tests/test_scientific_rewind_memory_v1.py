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
    MovieChatQuestion,
    MovieChatVideoRecord,
)
from research.reproductions.rewind_memory import (
    REWIND_MEMORY_PROGRAM,
    REWIND_REFERENCE_FIDELITY,
    ReWindMemoryBinding,
    ReWindMemoryStepRequest,
    ReWindMemoryStepResult,
    ReWindSelectionRequest,
    ReWindSelectionResult,
    build_rewind_cvpr2025_moviechat_test_cut,
    build_rewind_cvpr2025_study,
    rewind_cvpr2025_trial_protocol,
    rewind_memory_host,
    rewind_memory_initial_data,
)


_INSTRUCTION_SCHEMA = "rewind.instruction-embedding.tensor.v1"
_SUBCLIP_SCHEMA = "rewind.subclip-visual-features.tensor.v1"
_MEMORY_SCHEMA = "rewind.memory-bank.tensor.v1"
_SELECTED_SCHEMA = "rewind.selected-frame-features.tensor.v1"


def _store(root: Path) -> CanonicalJsonTensorContentStore:
    blob = DirectoryArtifactBlobStore(root / "blob")
    return CanonicalJsonTensorContentStore(
        blob,
        blob_store_identity_digest=canonical_digest({
            "provider": "rewind-test-blob-store",
            "root": str((root / "blob").resolve()),
        }),
    )


class _LearnedMemory:
    def __init__(self, store: CanonicalJsonTensorContentStore) -> None:
        self.store = store
        self.requests: list[ReWindMemoryStepRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "operator": "rewind-paper-contract-fixture",
            "implementation_revision": 1,
        })

    def step(
        self,
        request: ReWindMemoryStepRequest,
    ) -> ReWindMemoryStepResult:
        self.requests.append(request)
        added = request.subclip_ref.shape[0]
        total = request.processed_frame_count + added
        memory = tuple(
            (
                (float(frame), 0.0),
                (float(frame), 1.0),
            )
            for frame in range(total)
        )
        ref = self.store.put(memory, schema_id=_MEMORY_SCHEMA)
        return ReWindMemoryStepResult(
            memory_ref=ref,
            added_frame_count=added,
            model_receipt={
                "read_queries": request.read_query_count,
                "write_queries": request.write_query_count,
                "previous_memory": (
                    None
                    if request.previous_memory_ref is None
                    else request.previous_memory_ref.tensor_digest
                ),
            },
        )


class _Selector:
    def __init__(self, store: CanonicalJsonTensorContentStore) -> None:
        self.store = store
        self.requests: list[ReWindSelectionRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "selector": "rewind-dfs-paper-contract-fixture",
            "implementation_revision": 1,
        })

    def select(
        self,
        request: ReWindSelectionRequest,
    ) -> ReWindSelectionResult:
        self.requests.append(request)
        first = tuple(range(request.first_stage_count))
        selected = first[: request.final_frame_count]
        refs = tuple(
            self.store.put(
                tuple(
                    (float(index), float(token))
                    for token in range(request.selected_frame_tokens)
                ),
                schema_id=_SELECTED_SCHEMA,
            )
            for index in selected
        )
        return ReWindSelectionResult(
            instruction_selected_indices=first,
            selected_indices=selected,
            selected_frame_refs=refs,
            selector_receipt={
                "algorithm": "instruction-attention-then-DPC-KNN",
            },
        )


def _event(kind: str, payload: dict) -> dict:
    return {
        "event": {
            "kind": kind,
            "payload": payload,
            "source": "test",
        }
    }


def _subclip(
    store: CanonicalJsonTensorContentStore,
    *,
    start: int,
    count: int,
) -> dict:
    frames = tuple(
        tuple(
            (float(start + frame), float(token))
            for token in range(3)
        )
        for frame in range(count)
    )
    return store.put(frames, schema_id=_SUBCLIP_SCHEMA).payload()


def test_rewind_memory_enforces_stage_order_and_paper_token_geometry(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    instruction = store.put(
        ((1.0, 0.0), (0.0, 1.0)),
        schema_id=_INSTRUCTION_SCHEMA,
    )
    learned = _LearnedMemory(store)
    selector = _Selector(store)
    binding = ReWindMemoryBinding(
        tensor_store=store,
        learned_memory=learned,
        selector=selector,
    )
    journal = InMemoryMachineJournal()
    host = rewind_memory_host(journal=journal)
    machine_id = "memory:rewind:test"
    initial = rewind_memory_initial_data(instruction_ref=instruction)
    identity = {
        "memory_id": "rewind:test",
        "program_digest": REWIND_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }

    first = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "rewind.memory.ingest",
            {"subclip_ref": _subclip(store, start=0, count=6), "final": False},
        ),
        command_id_prefix="rewind:test",
    )
    assert first.status is MachineStatus.RUNNABLE
    assert first.previous_value["processed_frame_count"] == 6
    assert first.previous_value["memory_token_count"] == 12
    first_memory = TensorContentRef.from_payload(first.data["memory_ref"])
    assert first_memory.shape[:2] == (6, 2)

    with pytest.raises(
        RuntimeError,
        match="DFS requires completed Stage-1 memory",
    ):
        host.step_once(
            machine_id=machine_id,
            instance_identity=identity,
            binding=binding,
            initial_data=initial,
            payload=_event("rewind.memory.select", {}),
            command_id_prefix="rewind:test",
        )

    second = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "rewind.memory.ingest",
            {"subclip_ref": _subclip(store, start=6, count=4), "final": True},
        ),
        command_id_prefix="rewind:test",
    )
    assert second.previous_value["processed_frame_count"] == 10
    assert second.previous_value["memory_token_count"] == 20
    assert second.previous_value["video_complete"] is True
    assert learned.requests[1].previous_memory_ref is not None

    selected = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event("rewind.memory.select", {}),
        command_id_prefix="rewind:test",
    )
    assert tuple(selected.previous_value["instruction_selected_indices"]) == tuple(
        range(10)
    )
    assert tuple(selected.previous_value["selected_indices"]) == tuple(range(8))
    assert len(selected.previous_value["selected_frame_refs"]) == 8
    assert selector.requests[0].selected_frame_tokens == 32

    for payload in selected.previous_value["selected_frame_refs"]:
        ref = TensorContentRef.from_payload(payload)
        assert ref.shape[0] == 32
        assert store.verify(ref)

    read = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event("rewind.memory.read", {}),
        command_id_prefix="rewind:test",
    )
    assert len(read.previous_value["selected_frame_refs"]) == 8
    assert tuple(read.previous_value["llm_input_order"]) == (
        "memory",
        "separator",
        "selected_high_resolution_frames",
        "instruction",
    )
    assert len(journal.commits(machine_id)) == read.revision
    assert "float(frame)" not in str(read.data)


def test_rewind_fidelity_freezes_camera_ready_memory_and_dfs() -> None:
    fidelity = REWIND_REFERENCE_FIDELITY
    assert fidelity.perceiver_layers == 8
    assert fidelity.read_query_count == 32
    assert fidelity.write_query_count == 2
    assert fidelity.memory_tokens_per_frame == 2
    assert fidelity.dfs_instruction_selection_count == 64
    assert fidelity.dfs_final_frame_count == 8
    assert fidelity.dfs_selected_frame_tokens == 32
    assert fidelity.dfs_clustering == "DPC-KNN"
    assert fidelity.sampling_fps == 1


def _video(index: int) -> MovieChatVideoRecord:
    global_questions = tuple(
        MovieChatQuestion(
            question=f"global question {index}-{qa}",
            answer=f"global answer {index}-{qa}",
        )
        for qa in range(3)
    )
    breakpoint_questions = tuple(
        MovieChatQuestion(
            question=f"breakpoint question {index}-{qa}",
            answer=f"breakpoint answer {index}-{qa}",
            breakpoint_frame=10 * (qa + 1),
        )
        for qa in range(10)
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


def test_rewind_moviechat_study_binds_memory_and_selection_protocol() -> None:
    benchmark = build_rewind_cvpr2025_moviechat_test_cut(
        tuple(_video(index) for index in range(1000)),
        dataset_content_sha256=canonical_digest({
            "dataset": "rewind-moviechat-test-fixture",
        }),
    )
    protocol = rewind_cvpr2025_trial_protocol(benchmark)
    study = build_rewind_cvpr2025_study(benchmark)

    assert protocol.protocol_id == "rewind.cvpr2025.moviechat-1k.v1"
    method = next(
        row
        for row in study.binding_requirements.participants
        if row.participant_kind == "method"
    )
    assert method.method_id == "rewind"
    assert (
        study.trial_protocol_identity.configuration_digest
        == protocol.configuration_digest
    )
    names = {
        row.measurement_id
        for row in study.measurement_protocol.definitions
    }
    assert {
        "global_accuracy",
        "breakpoint_accuracy",
        "global_semantic_score",
        "breakpoint_semantic_score",
        "memory_tokens_per_frame",
        "dfs_selected_frame_count",
    }.issubset(names)
