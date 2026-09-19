from __future__ import annotations

from collections.abc import Sequence
import json
import math

from noetrium.contracts.systems.environment__embodied import (
    ActionKind,
    ActionSpec,
    EmbodiedActionCommand,
    EmbodimentKind,
    EmbodimentSpec,
    SensorModality,
    SensorSpec,
)

from .fidelity import PI05_OPENPI_FIDELITY


def build_pi05_embodiment_spec(
    *,
    embodiment_id: str = "pi05.reference",
    revision: str = "openpi-8999e55c",
) -> EmbodimentSpec:
    """Represent π0.5's observation/action contract with Noetrium's public embodied ABI."""

    fidelity = PI05_OPENPI_FIDELITY
    image_height, image_width = fidelity.image_resolution
    sensors = tuple(
        SensorSpec(
            sensor_id=image_key,
            modality=SensorModality.RGB,
            frame_id=image_key,
            dtype="float32",
            shape=(image_height, image_width, 3),
            metadata={"value_range": "[-1,1]", "model_role": "vision"},
        )
        for image_key in fidelity.image_keys
    ) + (
        SensorSpec(
            sensor_id="state",
            modality=SensorModality.PROPRIOCEPTION,
            frame_id="robot",
            dtype="float32",
            shape=(fidelity.action_dim,),
            metadata={
                "model_role": "state",
                "pi05_representation": fidelity.state_representation,
            },
        ),
    )
    actions = (
        ActionSpec(
            action_id="pi05.action_chunk",
            kind=ActionKind.OTHER,
            dimensions=fidelity.action_dim,
            dtype="float32",
            metadata={
                "action_horizon": fidelity.action_horizon,
                "representation": fidelity.action_representation,
                "flow_timestep_injection": fidelity.flow_timestep_injection,
            },
        ),
    )
    return EmbodimentSpec(
        embodiment_id=embodiment_id,
        revision=revision,
        kind=EmbodimentKind.OTHER,
        sensors=sensors,
        actions=actions,
        root_frame="robot",
        metadata={
            "reference_model": fidelity.model_type,
            "reference_source_commit": fidelity.source_commit,
            "max_token_len": fidelity.max_token_len,
        },
    )


def build_pi05_action_command(
    actions: Sequence[Sequence[float]],
    *,
    command_id: str,
    episode_id: str,
    sequence: int,
    issued_at_ns: int,
) -> EmbodiedActionCommand:
    """Encode one 50×32 π0.5 continuous action chunk without flattening its semantics."""

    fidelity = PI05_OPENPI_FIDELITY
    if len(actions) != fidelity.action_horizon:
        raise ValueError("π0.5 action chunk must contain exactly 50 action steps")

    normalized_rows: list[list[float]] = []
    for row in actions:
        if len(row) != fidelity.action_dim:
            raise ValueError("each π0.5 action step must contain exactly 32 values")
        normalized_row: list[float] = []
        for value in row:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("π0.5 action values must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("π0.5 action values must be finite")
            normalized_row.append(numeric)
        normalized_rows.append(normalized_row)

    normalized_payload = {
        "model_type": fidelity.model_type,
        "action_horizon": fidelity.action_horizon,
        "action_dim": fidelity.action_dim,
        "actions": normalized_rows,
    }
    raw_payload = json.dumps(
        normalized_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return EmbodiedActionCommand(
        command_id=command_id,
        episode_id=episode_id,
        action_id="pi05.action_chunk",
        sequence=sequence,
        raw_payload=raw_payload,
        normalized_payload=normalized_payload,
        issued_at_ns=issued_at_ns,
        metadata={
            "reference_source_commit": fidelity.source_commit,
            "chunk_shape": [fidelity.action_horizon, fidelity.action_dim],
        },
    )


__all__ = ["build_pi05_action_command", "build_pi05_embodiment_spec"]
