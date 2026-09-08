from noetrium_platform.capabilities.model.api import (
    ModelCapabilityInput,
    ModelCapabilityOutput,
    MultimodalMethodSpec,
    MultimodalPart,
    MultimodalRequest,
    MultimodalRequestCodecPort,
    MultimodalResponse,
)
import pytest
from noetrium_platform.capabilities.model.request.api import ContentRef


def _ref(char: str, media_type: str) -> ContentRef:
    return ContentRef(char * 64, 10, media_type)


def test_multimodal_contract_accepts_unknown_modalities_and_method_owned_schema() -> None:
    method = MultimodalMethodSpec(
        "paper.fusion.v7",
        "rev-3",
        "paper.fusion.input.v2",
        "paper.fusion.output.v4",
        input_modalities=(
            "application/x-token-lattice",
            "minecraft/voxel-observation",
            "application/x-point-cloud",
        ),
        output_modalities=("application/x-action-distribution",),
        parameters={"fusion": {"kind": "cross-attention"}, "window": 8},
    )
    request = MultimodalRequest(
        parts=(
            MultimodalPart(
                "world-state",
                _ref("a", "application/json"),
                modality_id="minecraft/voxel-observation",
                part_id="state-0",
                sequence_index=0,
                timestamp_ns=100,
                coordinate_frame="world",
            ),
            MultimodalPart(
                "latent",
                _ref("b", "application/octet-stream"),
                modality_id="application/x-token-lattice",
                part_id="latent-0",
                sequence_index=1,
                metadata={"shape": [2, 4], "layout": "nchw"},
            ),
            MultimodalPart(
                "geometry",
                _ref("c", "application/x-pcd"),
                modality_id="application/x-point-cloud",
                part_id="pc-0",
                sequence_index=2,
                duration_ns=500,
                source_refs=("episode:42",),
            ),
        ),
        method=method,
        metadata={"sampling": {"policy": "event-triggered"}},
    )
    assert request.schema_id == "model.multimodal.request.v1"
    assert request.parts[0].modality_id == "minecraft/voxel-observation"
    assert request.parts[1].metadata["shape"] == (2, 4)
    assert request.digest() != MultimodalRequest(request.parts, method=method).digest()
    response = MultimodalResponse(
        model_revision="qwen3-vl-paper-adapter-r1",
        parts=(MultimodalPart("action", _ref("d", "application/json"),
                              modality_id="application/x-action-distribution"),),
        method=method,
    )
    assert response.method is method
    assert response.parts[0].modality_id == "application/x-action-distribution"


def test_multimodal_contract_rejects_inline_bytes_and_invalid_provenance() -> None:
    with pytest.raises(TypeError, match="ContentRef"):
        MultimodalPart("image", b"raw")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        MultimodalPart("sensor", _ref("e", "custom/sensor"), sequence_index=-1)
    with pytest.raises(ValueError, match="non-empty"):
        MultimodalMethodSpec("", "r1", "in.v1", "out.v1")


def test_method_metadata_is_frozen_and_part_identity_changes_with_temporal_context() -> None:
    method = MultimodalMethodSpec(
        "paper.method",
        "r1",
        "input.v1",
        "output.v1",
        parameters={"temperature": 0.0},
    )
    part = MultimodalPart("x", _ref("f", "custom/x"), timestamp_ns=1)
    shifted = MultimodalPart("x", _ref("f", "custom/x"), timestamp_ns=2)
    assert method.parameters["temperature"] == 0.0
    assert part != shifted
    assert part.content.sha256 == shifted.content.sha256


def test_open_contract_reuses_generic_model_capability_and_provider_codec_seams() -> None:
    request = MultimodalRequest(
        (MultimodalPart("state", _ref("7", "application/json")),),
    )
    response = MultimodalResponse(model_revision="r1", text="ok")
    assert isinstance(request, ModelCapabilityInput)
    assert isinstance(response, ModelCapabilityOutput)

    class Codec:
        def encode(self, value, content):
            return {"part_count": len(value.parts)}

    codec = Codec()
    assert isinstance(codec, MultimodalRequestCodecPort)
    assert codec.encode(request, object())["part_count"] == 1
