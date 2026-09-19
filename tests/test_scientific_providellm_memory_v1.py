from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
)
from research.reproductions.providellm_memory.fidelity import (
    PROVIDELLM_REFERENCE_FIDELITY,
)
from research.reproductions.providellm_memory.memory import (
    PROVIDELLM_MEMORY_PROGRAM,
    providellm_memory_host,
    providellm_memory_initial_data,
)


def _event(kind: str, payload: dict | None = None) -> dict:
    return {
        "event": {
            "kind": kind,
            "payload": {} if payload is None else payload,
        }
    }


def test_providellm_interleaved_cache_verbalizes_and_evicts_by_token_type() -> None:
    journal = InMemoryMachineJournal()
    host = providellm_memory_host(journal=journal)
    machine_id = "memory:providellm:test"
    initial = providellm_memory_initial_data(
        short_capacity=2,
        long_capacity=2,
        duplicate_horizon=1,
    )
    identity = {
        "memory_id": "providellm:test",
        "program_digest": PROVIDELLM_MEMORY_PROGRAM.program_digest,
    }

    rows = (
        ("visual:0", "cut onion"),
        ("visual:1", "cut onion"),
        ("visual:2", "heat pan"),
        ("visual:3", "heat pan"),
        ("visual:4", "add eggs"),
        ("visual:5", "whisk eggs"),
    )
    executions = []
    for visual_ref, prediction in rows:
        executions.append(
            host.step_once(
                machine_id=machine_id,
                instance_identity=identity,
                binding=None,
                initial_data=initial,
                payload=_event(
                    "providellm.memory.frame",
                    {
                        "visual_token_ref": visual_ref,
                        "prediction_text": prediction,
                    },
                ),
                command_id_prefix="providellm:test",
            )
        )

    assert all(row.status is MachineStatus.RUNNABLE for row in executions)
    assert executions[2].previous_value["verbalized_text"] == "cut onion"
    assert executions[3].previous_value["verbalized_text"] is None
    assert executions[4].previous_value["verbalized_text"] == "heat pan"
    assert executions[5].previous_value["verbalized_text"] == "add eggs"
    assert executions[5].previous_value["long_token_count"] == 2
    assert executions[5].previous_value["short_token_count"] == 2
    assert executions[5].data["short_eviction_count"] == 4
    assert executions[5].data["long_eviction_count"] == 1
    assert executions[5].data["verbalized_insert_count"] == 3

    readout = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=None,
        initial_data=initial,
        payload=_event("providellm.memory.readout"),
        command_id_prefix="providellm:test",
    )
    tokens = tuple(readout.previous_value["tokens"])
    assert tuple(row["text"] for row in tokens if row["kind"] == "long_text") == (
        "heat pan",
        "add eggs",
    )
    assert tuple(
        row["visual_token_ref"] for row in tokens if row["kind"] == "visual"
    ) == ("visual:4", "visual:5")
    assert all(
        row.get("marker") == "<L>"
        for row in tokens
        if row["kind"] == "long_text"
    )
    assert len(journal.commits(machine_id)) == readout.revision


def test_providellm_iccv2025_fidelity_freezes_cache_contract() -> None:
    fidelity = PROVIDELLM_REFERENCE_FIDELITY

    assert fidelity.venue == "ICCV 2025"
    assert fidelity.long_term_token_type == "verbalized_text"
    assert fidelity.short_term_token_type == "detr_qformer_visual"
    assert fidelity.cache_type == "multimodal_interleaved_fifo"
    assert fidelity.single_entry_point is True
    assert fidelity.separate_short_long_exits is True
    assert fidelity.long_term_marker == "<L>"
    assert fidelity.typical_short_term_min_seconds == 8
    assert fidelity.typical_short_term_max_seconds == 16
    assert fidelity.runtime_short_term_span_seconds == 16
    assert fidelity.runtime_long_term_span_seconds == 128
    assert fidelity.one_hour_verbalized_token_average == 630
    assert fidelity.reported_token_reduction_factor == 22.0
    assert fidelity.reported_per_frame_fps == 10.0
    assert fidelity.reported_streaming_dialogue_fps == 24.6
    assert fidelity.reported_gpu_memory_gb == 2.0
    assert fidelity.official_streaming_interleave_code_released is False
    assert fidelity.official_detr_qformer_code_released is True
