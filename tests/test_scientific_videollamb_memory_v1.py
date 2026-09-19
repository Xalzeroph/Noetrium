from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from research.reproductions.videollamb_memory.fidelity import (
    VIDEOLLAMB_REFERENCE_FIDELITY,
)
from research.reproductions.videollamb_memory.memory import (
    VIDEOLLAMB_MEMORY_PROGRAM,
    VideoLLaMBMemoryBinding,
    VideoLLaMBRetrievalResult,
    VideoLLaMBSegmentBridgeResult,
    videollamb_memory_host,
    videollamb_memory_initial_data,
)


class _Bridge:
    def __init__(self) -> None:
        self.bridge_requests = []
        self.retrieval_requests = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "videollamb-memory-bridge",
            "source_commit": VIDEOLLAMB_REFERENCE_FIDELITY.source_commit,
        })

    def bridge(self, request):
        self.bridge_requests.append(request)
        index = request.segment_index
        return VideoLLaMBSegmentBridgeResult(
            projected_segment_ref=f"projected:{index}",
            read_memory_ref=f"bridge-memory:{index}",
            provider_receipt={"segment_index": index},
        )

    def retrieve(self, request):
        self.retrieval_requests.append(request)
        index = len(self.retrieval_requests) - 1
        return VideoLLaMBRetrievalResult(
            refreshed_memory_ref=f"retrieved-memory:{index}",
            provider_receipt={
                "cache_size": len(request.memory_cache_refs),
            },
        )


def _event(kind: str, payload: dict | None = None) -> dict:
    return {
        "event": {
            "kind": kind,
            "payload": {} if payload is None else payload,
        }
    }


def test_videollamb_recurrent_memory_bridge_persists_cache_across_segments() -> None:
    journal = InMemoryMachineJournal()
    bridge = _Bridge()
    binding = VideoLLaMBMemoryBinding(bridge=bridge)
    host = videollamb_memory_host(journal=journal)
    machine_id = "memory:videollamb:test"
    initial = videollamb_memory_initial_data()
    identity = {
        "memory_id": "videollamb:test",
        "program_digest": VIDEOLLAMB_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }

    first = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "videollamb.memory.segment",
            {"segment_feature_ref": "segment:0"},
        ),
        command_id_prefix="videollamb:test",
    )
    assert first.status is MachineStatus.RUNNABLE
    assert first.previous_value["segment_index"] == 0
    assert first.previous_value["memory_cache_size"] == 1
    assert first.data["recurrent_memory_ref"] == "retrieved-memory:0"
    assert tuple(first.data["memory_cache_refs"]) == ("bridge-memory:0",)
    assert bridge.bridge_requests[0].previous_memory_ref is None
    assert bridge.bridge_requests[0].memory_token_count == 32
    assert bridge.retrieval_requests[0].memory_cache_refs == ("bridge-memory:0",)

    second = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "videollamb.memory.segment",
            {"segment_feature_ref": "segment:1"},
        ),
        command_id_prefix="videollamb:test",
    )
    assert second.previous_value["segment_index"] == 1
    assert second.previous_value["memory_cache_size"] == 2
    assert bridge.bridge_requests[1].previous_memory_ref == "retrieved-memory:0"
    assert bridge.retrieval_requests[1].memory_cache_refs == (
        "bridge-memory:0",
        "bridge-memory:1",
    )
    assert second.data["recurrent_memory_ref"] == "retrieved-memory:1"
    assert tuple(second.data["projected_segment_refs"]) == (
        "projected:0",
        "projected:1",
    )

    readout = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event("videollamb.memory.readout"),
        command_id_prefix="videollamb:test",
    )
    assert readout.previous_value["segment_count"] == 2
    assert tuple(readout.previous_value["memory_cache_refs"]) == (
        "bridge-memory:0",
        "bridge-memory:1",
    )
    assert len(journal.commits(machine_id)) == readout.revision


def test_videollamb_iccv2025_fidelity_freezes_recurrent_memory_contract() -> None:
    fidelity = VIDEOLLAMB_REFERENCE_FIDELITY

    assert fidelity.venue == "ICCV 2025"
    assert fidelity.recurrent_memory_tokens is True
    assert fidelity.memory_bridge_layers is True
    assert fidelity.memory_cache_retrieval is True
    assert fidelity.scene_tiling is True
    assert fidelity.bridge_transformer_layers == 1
    assert fidelity.training_frames == 16
    assert fidelity.training_segments == 4
    assert fidelity.demonstrated_max_frames == 320
    assert fidelity.demonstrated_gpu == "NVIDIA A100"
    assert fidelity.linear_gpu_memory_scaling is True
    assert fidelity.training_free_streaming_captioning is True
    assert fidelity.videoqa_improvement_points == 4.2
    assert fidelity.egocentric_planning_improvement_points == 2.06
    assert fidelity.source_commit == "962837c5b310559de18b375eaee20561123bb54c"
