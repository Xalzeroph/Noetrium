from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.evidence.artifact.content.providers import (
    CanonicalJsonTensorContentStore,
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from research.benchmarks.lvu import LVU_BENCHMARK_ID, LVUVideoRecord
from research.reproductions.adacm2_memory import (
    ADACM2_LVU_PROTOCOL,
    ADACM2_MEMORY_PROGRAM,
    ADACM2_REFERENCE_FIDELITY,
    AdaCM2AttentionRequest,
    AdaCM2AttentionScores,
    AdaCM2MemoryBinding,
    AdaCM2PartitionInterpretation,
    AdaCM2ReductionSpec,
    adacm2_memory_host,
    adacm2_memory_initial_data,
    build_adacm2_lvu_ambiguity_studies,
    build_adacm2_lvu_cut,
    reduce_adacm2_cache,
)


_QUERY_SCHEMA = "adacm2.query-text.tensor.v1"
_FRAME_KEY_SCHEMA = "adacm2.frame-key.tensor.v1"
_FRAME_VALUE_SCHEMA = "adacm2.frame-value.tensor.v1"


def _store(root: Path) -> CanonicalJsonTensorContentStore:
    blob = DirectoryArtifactBlobStore(root / "blob")
    return CanonicalJsonTensorContentStore(
        blob,
        blob_store_identity_digest=canonical_digest({
            "provider": "adacm2-test-blob-store",
            "root": str((root / "blob").resolve()),
        }),
    )


class _Attention:
    def __init__(self) -> None:
        self.requests: list[AdaCM2AttentionRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "attention": "adacm2-test-cross-modal",
            "implementation_revision": 1,
        })

    def score(
        self,
        request: AdaCM2AttentionRequest,
    ) -> AdaCM2AttentionScores:
        self.requests.append(request)
        return AdaCM2AttentionScores(
            tuple(float(index) for index in range(request.token_count)),
            model_receipt={
                "reduction": "sum-over-query-text-rows",
                "layer_id": request.layer_id,
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


def _frame_ref(
    store: CanonicalJsonTensorContentStore,
    *,
    schema_id: str,
    offset: int,
    count: int = 100,
) -> dict:
    return store.put(
        tuple(
            (float(offset + index), float(index % 7))
            for index in range(count)
        ),
        schema_id=schema_id,
    ).payload()


def test_adacm2_preserves_eq6_eq8_paper_inconsistency_as_treatments() -> None:
    eq6 = AdaCM2ReductionSpec(
        AdaCM2PartitionInterpretation.EQ6_LITERAL,
    )
    eq8 = AdaCM2ReductionSpec(
        AdaCM2PartitionInterpretation.EQ8_CONSISTENT,
    )
    fidelity = ADACM2_REFERENCE_FIDELITY

    assert eq6.previous_fraction == pytest.approx(0.1)
    assert eq6.recent_fraction == pytest.approx(0.9)
    assert eq6.operational_retention_factor == pytest.approx(0.91)
    assert eq8.previous_fraction == pytest.approx(0.9)
    assert eq8.recent_fraction == pytest.approx(0.1)
    assert eq8.operational_retention_factor == pytest.approx(0.19)
    assert eq6.stated_theoretical_retention_factor == pytest.approx(0.19)
    assert eq8.stated_theoretical_retention_factor == pytest.approx(0.19)
    assert fidelity.eq6_and_eq8_are_jointly_inconsistent is True

    keys = tuple(f"k{index}" for index in range(100))
    values = tuple(f"v{index}" for index in range(100))

    eq6_scores = AdaCM2AttentionScores(
        tuple(float(index) for index in range(10))
    )
    k6, v6, receipt6 = reduce_adacm2_cache(
        keys,
        values,
        eq6_scores,
        spec=eq6,
    )
    assert len(k6) == 91
    assert len(v6) == 91
    assert receipt6.previous_length == 10
    assert receipt6.recent_length == 90
    assert receipt6.retained_previous_indices == (9,)
    assert k6[0] == "k9"
    assert k6[1] == "k10"

    eq8_scores = AdaCM2AttentionScores(
        tuple(float(index) for index in range(90))
    )
    k8, v8, receipt8 = reduce_adacm2_cache(
        keys,
        values,
        eq8_scores,
        spec=eq8,
    )
    assert len(k8) == 19
    assert len(v8) == 19
    assert receipt8.previous_length == 90
    assert receipt8.recent_length == 10
    assert receipt8.retained_previous_indices == tuple(range(81, 90))
    assert k8[:9] == tuple(f"k{index}" for index in range(81, 90))
    assert k8[9:] == tuple(f"k{index}" for index in range(90, 100))


def test_adacm2_memory_program_reduces_kv_cache_with_shared_indices(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    query_ref = store.put(
        ((1.0, 0.0), (0.0, 1.0)),
        schema_id=_QUERY_SCHEMA,
    )
    attention = _Attention()
    spec = AdaCM2ReductionSpec(
        AdaCM2PartitionInterpretation.EQ8_CONSISTENT,
    )
    binding = AdaCM2MemoryBinding(
        tensor_store=store,
        attention=attention,
        spec=spec,
    )
    journal = InMemoryMachineJournal()
    host = adacm2_memory_host(journal=journal)
    machine_id = "memory:adacm2:test"
    initial = adacm2_memory_initial_data(
        query_text_ref=query_ref,
        interpretation=spec.interpretation,
    )
    identity = {
        "memory_id": "adacm2:test",
        "program_digest": ADACM2_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }

    first = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "adacm2.cache.update",
            {
                "layer_id": "qformer.layer.0",
                "key_ref": _frame_ref(
                    store,
                    schema_id=_FRAME_KEY_SCHEMA,
                    offset=0,
                ),
                "value_ref": _frame_ref(
                    store,
                    schema_id=_FRAME_VALUE_SCHEMA,
                    offset=1000,
                ),
            },
        ),
        command_id_prefix="adacm2:test",
    )

    assert first.status is MachineStatus.RUNNABLE
    receipt = first.previous_value["reduction_receipt"]
    assert receipt["before_length"] == 100
    assert receipt["previous_length"] == 90
    assert receipt["recent_length"] == 10
    assert receipt["retained_previous_length"] == 9
    assert first.previous_value["cache_length"] == 19
    assert len(attention.requests) == 1
    assert attention.requests[0].token_count == 90

    second = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "adacm2.cache.update",
            {
                "layer_id": "qformer.layer.0",
                "key_ref": _frame_ref(
                    store,
                    schema_id=_FRAME_KEY_SCHEMA,
                    offset=100,
                ),
                "value_ref": _frame_ref(
                    store,
                    schema_id=_FRAME_VALUE_SCHEMA,
                    offset=1100,
                ),
            },
        ),
        command_id_prefix="adacm2:test",
    )
    assert second.previous_value["before_length"] == 119
    assert second.previous_value["cache_length"] == 23
    assert len(attention.requests) == 2

    read = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "adacm2.cache.read",
            {"layer_id": "qformer.layer.0"},
        ),
        command_id_prefix="adacm2:test",
    )
    assert read.previous_value["layer_count"] == 1
    assert read.previous_value["interpretation"] == "eq8_consistent"
    assert read.previous_value[
        "operational_retention_factor"
    ] == pytest.approx(0.19)
    assert read.previous_value[
        "stated_theoretical_retention_factor"
    ] == pytest.approx(0.19)
    assert len(journal.commits(machine_id)) == read.revision


def _lvu_record(
    split_id: str,
    video_id: str,
    *,
    duration_seconds: int,
) -> LVUVideoRecord:
    annotations = tuple(
        (task, f"{task}-label")
        for task in ADACM2_LVU_PROTOCOL.task_ids
    )
    answers = tuple(
        (task, "(a)")
        for task in ADACM2_LVU_PROTOCOL.task_ids
    )
    return LVUVideoRecord(
        split_id=split_id,
        video_id=video_id,
        duration_seconds=duration_seconds,
        num_frames=duration_seconds * ADACM2_LVU_PROTOCOL.fps,
        annotations=annotations,
        answer_codes=answers,
        content_digest=canonical_digest({
            "split": split_id,
            "video": video_id,
            "duration_seconds": duration_seconds,
            "annotations": annotations,
        }),
    )


def test_adacm2_lvu_uses_full_video_projection_and_two_ambiguity_studies() -> None:
    benchmark = build_adacm2_lvu_cut(
        (
            _lvu_record(
                "train",
                "movie-train",
                duration_seconds=120,
            ),
            _lvu_record(
                "test",
                "movie-test",
                duration_seconds=180,
            ),
        ),
        dataset_content_sha256=canonical_digest({
            "dataset": "lvu-1.0-adacm2-fixture",
        }),
    )

    assert benchmark.benchmark_id == LVU_BENCHMARK_ID
    test_tasks = benchmark.selected_tasks("test")
    assert len(test_tasks) == 7
    assert {
        task.family for task in test_tasks
    } == {
        f"lvu_{task}" for task in ADACM2_LVU_PROTOCOL.task_ids
    }
    assert all(task.task_id.endswith(":full-video") for task in test_tasks)
    assert all(
        "projection:full-video-stream" in task.lineage_refs
        for task in test_tasks
    )

    eq6_study, eq8_study = build_adacm2_lvu_ambiguity_studies(
        benchmark
    )
    assert eq6_study.method.treatment == "eq6_literal"
    assert eq8_study.method.treatment == "eq8_consistent"
    assert (
        eq6_study.trial_protocol_identity.configuration_digest
        != eq8_study.trial_protocol_identity.configuration_digest
    )
    assert eq6_study.benchmark_split_id == "test"
    assert eq8_study.benchmark_split_id == "test"
    names = {
        row.name for row in eq8_study.measurement_protocol.definitions
    }
    assert {
        "task_accuracy",
        "peak_cache_length",
        "cache_retention_ratio",
        "paper_stated_retention_factor",
    }.issubset(names)
