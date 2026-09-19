from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from noetrium_platform.capabilities.environment.runtime.api import freeze_json_mapping
from noetrium_platform.capabilities.environment.runtime.runtime.state_machine import (
    StateMachineCheckpointError as FacadeCheckpointError,
)
from noetrium_platform.capabilities.environment.runtime.runtime.state_machine_checkpoint import (
    DecodedStateMachineCheckpoint,
    StateMachineCheckpointCodec,
    StateMachineCheckpointError,
)


def _codec() -> StateMachineCheckpointCodec:
    return StateMachineCheckpointCodec(
        session_id="codec-session",
        environment_generation="a" * 64,
        provider_instance_id="codec-world:codec-session",
    )


def test_checkpoint_error_identity_is_preserved_by_runtime_facade() -> None:
    assert FacadeCheckpointError is StateMachineCheckpointError


def test_checkpoint_codec_roundtrip_returns_frozen_snapshot() -> None:
    codec = _codec()
    payload = codec.encode(
        state=freeze_json_mapping({"value": 0}, field="test.state"),
        observation_sequence=0,
        actions={},
    )

    decoded = codec.decode(payload)

    assert isinstance(decoded, DecodedStateMachineCheckpoint)
    assert decoded.state["value"] == 0
    assert decoded.observation_sequence == 0
    assert decoded.actions == ()
    with pytest.raises(FrozenInstanceError):
        decoded.observation_sequence = 1


def test_checkpoint_codec_rejects_state_digest_tamper() -> None:
    codec = _codec()
    payload = codec.encode(
        state=freeze_json_mapping({"value": 0}, field="test.state"),
        observation_sequence=0,
        actions={},
    )
    document = json.loads(payload)
    document["state_digest"] = "0" * 64

    with pytest.raises(StateMachineCheckpointError, match="invalid or incompatible"):
        codec.decode(json.dumps(document).encode("utf-8"))
