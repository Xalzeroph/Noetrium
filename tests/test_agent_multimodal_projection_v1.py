from noetrium_platform.capabilities.model.api import MultimodalPart
from noetrium_platform.capabilities.model.request.api import ContentRef
from noetrium_platform.capabilities.participant.agent.api.cognition import AgentObservation
from noetrium_platform.capabilities.participant.agent.runtime import AgentMultimodalObservationProjector


def _ref(char: str, media_type: str) -> ContentRef:
    return ContentRef(char * 64, 4, media_type)


def test_generic_agent_projection_preserves_arbitrary_parts_and_provenance() -> None:
    observation = AgentObservation("obs-1", "generation-1", {"health": 20})
    parts = (
        MultimodalPart("rgb", _ref("a", "image/png"), modality_id="camera/rgb",
                       sequence_index=0, timestamp_ns=10, coordinate_frame="agent"),
        MultimodalPart("depth", _ref("b", "application/x-depth-f16"),
                       modality_id="sensor/depth-f16", sequence_index=1, timestamp_ns=10,
                       metadata={"shape": [480, 640]}),
        MultimodalPart("plan", _ref("c", "application/x-token-lattice"),
                       modality_id="paper/custom-latent", sequence_index=2),
    )
    projected = AgentMultimodalObservationProjector().project(
        observation, parts, observation_modality="world+paper-method",
        extra_state={"method_id": "paper.fusion.v2"},
    )
    payload = projected.state["multimodal"]
    assert projected.modality == "world+paper-method"
    assert payload["part_count"] == 3
    assert payload["parts"][1]["modality_id"] == "sensor/depth-f16"
    assert payload["parts"][2]["metadata"] == {}
    assert projected.state["method_id"] == "paper.fusion.v2"
    assert "a" * 64 in projected.artifact_refs
    assert "b" * 64 in projected.artifact_refs
    assert "c" * 64 in projected.artifact_refs
    assert projected.state_digest != observation.state_digest


def test_generic_agent_projection_rejects_untyped_parts() -> None:
    observation = AgentObservation("obs-2", "generation-1", {})
    try:
        AgentMultimodalObservationProjector().project(observation, (b"raw",))  # type: ignore[arg-type]
    except TypeError as exc:
        assert "MultimodalPart" in str(exc)
    else:
        raise AssertionError("untyped multimodal part was accepted")
