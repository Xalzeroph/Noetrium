import json

import pytest

from noetrium.contracts.systems.environment__embodied import (
    ActionKind,
    EmbodimentKind,
    SensorModality,
)
from research.reproductions.pi05_openpi import (
    PI05_OPENPI_FIDELITY,
    build_pi05_action_command,
    build_pi05_embodiment_spec,
)


def test_pi05_fidelity_pins_release_observation_and_action_contract() -> None:
    assert PI05_OPENPI_FIDELITY.model_type == "pi05"
    assert PI05_OPENPI_FIDELITY.image_resolution == (224, 224)
    assert PI05_OPENPI_FIDELITY.image_keys == (
        "base_0_rgb",
        "left_wrist_0_rgb",
        "right_wrist_0_rgb",
    )
    assert PI05_OPENPI_FIDELITY.action_horizon == 50
    assert PI05_OPENPI_FIDELITY.action_dim == 32
    assert PI05_OPENPI_FIDELITY.max_token_len == 200
    assert PI05_OPENPI_FIDELITY.state_representation == "discrete_language_tokens"


def test_pi05_maps_three_cameras_state_and_action_chunk_to_public_embodied_abi() -> None:
    spec = build_pi05_embodiment_spec()

    assert spec.kind is EmbodimentKind.OTHER
    assert [sensor.sensor_id for sensor in spec.sensors] == [
        "base_0_rgb",
        "left_wrist_0_rgb",
        "right_wrist_0_rgb",
        "state",
    ]
    for sensor in spec.sensors[:3]:
        assert sensor.modality is SensorModality.RGB
        assert sensor.shape == (224, 224, 3)
    assert spec.sensors[-1].modality is SensorModality.PROPRIOCEPTION
    assert spec.sensors[-1].shape == (32,)

    action = spec.actions[0]
    assert action.action_id == "pi05.action_chunk"
    assert action.kind is ActionKind.OTHER
    assert action.dimensions == 32
    assert action.metadata["action_horizon"] == 50
    assert action.metadata["representation"] == "continuous_float32_chunk"


def test_pi05_action_command_preserves_50_by_32_chunk_and_exact_raw_evidence() -> None:
    chunk = [[float(step * 32 + column) for column in range(32)] for step in range(50)]
    command = build_pi05_action_command(
        chunk,
        command_id="cmd-1",
        episode_id="episode-1",
        sequence=1,
        issued_at_ns=1,
    )

    assert command.action_id == "pi05.action_chunk"
    assert command.normalized_payload["action_horizon"] == 50
    assert command.normalized_payload["action_dim"] == 32
    assert len(command.normalized_payload["actions"]) == 50
    assert len(command.normalized_payload["actions"][0]) == 32
    decoded = json.loads(command.raw_payload.decode("utf-8"))
    assert decoded == command.normalized_payload
    assert len(command.raw_payload_sha256) == 64


def test_pi05_action_command_fails_closed_on_shape_or_numeric_drift() -> None:
    with pytest.raises(ValueError, match="exactly 50"):
        build_pi05_action_command(
            [[0.0] * 32],
            command_id="cmd-1",
            episode_id="episode-1",
            sequence=1,
            issued_at_ns=1,
        )
    with pytest.raises(ValueError, match="exactly 32"):
        build_pi05_action_command(
            [[0.0] * 31 for _ in range(50)],
            command_id="cmd-1",
            episode_id="episode-1",
            sequence=1,
            issued_at_ns=1,
        )
    bad = [[0.0] * 32 for _ in range(50)]
    bad[0][0] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        build_pi05_action_command(
            bad,
            command_id="cmd-1",
            episode_id="episode-1",
            sequence=1,
            issued_at_ns=1,
        )
