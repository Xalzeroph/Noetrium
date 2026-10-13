from __future__ import annotations

"""Pure client-state checkpoint codec for a Minecraft environment session.

World bytes are supplied by the authoritative checkpoint port.  This module
only validates and serializes the session projection that must travel with
those bytes; it does not stop bridges or mutate a live provider.
"""

import base64
from dataclasses import dataclass
import hashlib
from typing import Mapping, Protocol

from noetrium_platform.capabilities.environment.api import ActionReconciliationDisposition, Observation
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_bytes

from ..api.ports import MinecraftCheckpointPort
from .state import MinecraftStateProjection


@dataclass(frozen=True, slots=True)
class MinecraftActionResolution:
    request_digest: str
    disposition: ActionReconciliationDisposition
    invocation_unit_digest: str | None = None
    authorization_unit_digest: str | None = None

    def __post_init__(self) -> None:
        lineage = (self.invocation_unit_digest, self.authorization_unit_digest)
        if (lineage[0] is None) != (lineage[1] is None):
            raise ValueError("Minecraft action resolution Unit lineage must be complete")
        for value in lineage:
            if value is not None and (
                len(value) != 64
                or value != value.lower()
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError("Minecraft action resolution Unit digest is invalid")


@dataclass(frozen=True, slots=True)
class MinecraftCheckpointSnapshot:
    world_payload: bytes
    observation_sequence: int
    actions: dict[str, MinecraftActionResolution]
    state: MinecraftStateProjection
    last_observation: Observation | None


class MinecraftSessionCheckpointPort(Protocol):
    """Session-side persistence seam; world bytes remain provider-owned."""

    schema: str

    def capture(
        self,
        *,
        provider: MinecraftCheckpointPort,
        session_id: str,
        generation: str,
        observation_sequence: int,
        actions: Mapping[str, MinecraftActionResolution],
        state: MinecraftStateProjection,
        last_observation: Observation | None,
    ) -> tuple[bytes, int]: ...

    def decode(
        self,
        payload: bytes,
        *,
        session_id: str,
        generation: str,
        max_entities: int,
    ) -> MinecraftCheckpointSnapshot: ...


class MinecraftCheckpointCodec:
    """Encode/decode the versioned session-side checkpoint envelope."""

    SCHEMA = "minecraft-environment-session.v4"
    LEGACY_SCHEMA = "minecraft-environment-session.v3"

    @staticmethod
    def _is_sha256(value: object) -> bool:
        return (
            isinstance(value, str)
            and value == value.lower()
            and len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
        )

    @classmethod
    def capture(
        cls,
        *,
        provider: MinecraftCheckpointPort,
        session_id: str,
        generation: str,
        observation_sequence: int,
        actions: Mapping[str, MinecraftActionResolution],
        state: MinecraftStateProjection,
        last_observation: Observation | None,
    ) -> tuple[bytes, int]:
        world_payload = provider.capture(session_id=session_id, context=None)
        payload = canonical_bytes(
            {
                "schema_version": cls.SCHEMA,
                "session_id": session_id,
                "environment_generation": generation,
                "world_payload_sha256": hashlib.sha256(world_payload).hexdigest(),
                "world_payload_base64": base64.b64encode(world_payload).decode("ascii"),
                "observation_sequence": observation_sequence,
                "actions": [
                    {
                        "action_id": action_id,
                        "request_digest": resolution.request_digest,
                        "effect_disposition": resolution.disposition.value,
                        "invocation_unit_digest": resolution.invocation_unit_digest,
                        "authorization_unit_digest": resolution.authorization_unit_digest,
                    }
                    for action_id, resolution in sorted(actions.items())
                ],
                "state": state.compact(),
                "state_digest": state.snapshot_digest(),
                "last_observation": None
                if last_observation is None
                else {
                    "observation_id": last_observation.observation_id,
                    "generation": last_observation.generation,
                    "payload": last_observation.payload,
                    "artifact_refs": last_observation.artifact_refs,
                },
            }
        )
        return payload, len(world_payload)

    @classmethod
    def decode(
        cls,
        payload: bytes,
        *,
        session_id: str,
        generation: str,
        max_entities: int,
    ) -> MinecraftCheckpointSnapshot:
        import json

        document = json.loads(payload.decode("utf-8"))
        if not isinstance(document, Mapping):
            raise TypeError("checkpoint root must be a mapping")
        expected_fields = {
            "schema_version",
            "session_id",
            "environment_generation",
            "world_payload_sha256",
            "world_payload_base64",
            "observation_sequence",
            "actions",
            "state",
            "state_digest",
            "last_observation",
        }
        if set(document) != expected_fields:
            raise ValueError("Minecraft environment checkpoint schema fields mismatch")
        schema_version = document["schema_version"]
        if schema_version not in {cls.SCHEMA, cls.LEGACY_SCHEMA}:
            raise ValueError("unsupported Minecraft environment checkpoint schema")
        if document["session_id"] != session_id:
            raise ValueError("Minecraft environment checkpoint session mismatch")
        if document["environment_generation"] != generation:
            raise ValueError("Minecraft environment checkpoint generation mismatch")
        world_payload_base64 = document["world_payload_base64"]
        if not isinstance(world_payload_base64, str):
            raise TypeError("Minecraft world checkpoint payload encoding is invalid")
        world_payload = base64.b64decode(world_payload_base64, validate=True)
        world_payload_sha256 = document["world_payload_sha256"]
        if not cls._is_sha256(world_payload_sha256):
            raise TypeError("Minecraft world checkpoint payload digest is invalid")
        if hashlib.sha256(world_payload).hexdigest() != world_payload_sha256:
            raise ValueError("Minecraft world checkpoint payload digest mismatch")
        state_raw = document["state"]
        if not isinstance(state_raw, Mapping):
            raise TypeError("Minecraft checkpoint state must be a mapping")
        restored_state = MinecraftStateProjection.from_compact(
            state_raw,
            max_entities=max_entities,
        )
        state_digest = document["state_digest"]
        if not cls._is_sha256(state_digest):
            raise TypeError("Minecraft state checkpoint digest is invalid")
        if restored_state.snapshot_digest() != state_digest:
            raise ValueError("Minecraft state checkpoint digest mismatch")
        observation_sequence = document["observation_sequence"]
        if (
            isinstance(observation_sequence, bool)
            or not isinstance(observation_sequence, int)
            or observation_sequence < 0
        ):
            raise ValueError("Minecraft checkpoint observation sequence is invalid")
        action_rows = document["actions"]
        if not isinstance(action_rows, list):
            raise ValueError("Minecraft checkpoint actions must be a list")
        restored_actions: dict[str, MinecraftActionResolution] = {}
        for row in action_rows:
            if not isinstance(row, Mapping):
                raise ValueError("Minecraft checkpoint action row is invalid")
            action_id = row.get("action_id")
            request_digest = row.get("request_digest")
            raw_disposition = row.get("effect_disposition")
            expected_action_fields = (
                {"action_id", "request_digest", "effect_disposition"}
                if schema_version == cls.LEGACY_SCHEMA
                else {
                    "action_id", "request_digest", "effect_disposition",
                    "invocation_unit_digest", "authorization_unit_digest",
                }
            )
            if (
                set(row) != expected_action_fields
                or not isinstance(action_id, str)
                or not action_id.strip()
                or action_id in restored_actions
                or not cls._is_sha256(request_digest)
                or not isinstance(raw_disposition, str)
            ):
                raise ValueError("Minecraft checkpoint action identity set is invalid")
            invocation_unit_digest = row.get("invocation_unit_digest")
            authorization_unit_digest = row.get("authorization_unit_digest")
            if schema_version == cls.SCHEMA and (
                (invocation_unit_digest is None) != (authorization_unit_digest is None)
                or any(
                    value is not None and not cls._is_sha256(value)
                    for value in (invocation_unit_digest, authorization_unit_digest)
                )
            ):
                raise ValueError("Minecraft checkpoint action Unit lineage is invalid")
            try:
                disposition = ActionReconciliationDisposition(raw_disposition)
            except ValueError as exc:
                raise ValueError(
                    "Minecraft checkpoint action effect disposition is invalid"
                ) from exc
            restored_actions[action_id] = MinecraftActionResolution(
                request_digest=request_digest,
                disposition=disposition,
                invocation_unit_digest=invocation_unit_digest,
                authorization_unit_digest=authorization_unit_digest,
            )
        last_raw = document["last_observation"]
        restored_last = None
        if last_raw is not None:
            if not isinstance(last_raw, Mapping):
                raise TypeError("Minecraft checkpoint last observation is invalid")
            if set(last_raw) != {
                "observation_id",
                "generation",
                "payload",
                "artifact_refs",
            }:
                raise ValueError("Minecraft checkpoint observation schema mismatch")
            observation_id = last_raw["observation_id"]
            observation_generation = last_raw["generation"]
            if not isinstance(last_raw["payload"], Mapping):
                raise TypeError("Minecraft checkpoint observation payload is invalid")
            artifact_refs = last_raw["artifact_refs"]
            if (
                not isinstance(observation_id, str)
                or not observation_id.strip()
                or not isinstance(observation_generation, str)
                or not isinstance(artifact_refs, list)
                or any(not isinstance(ref, str) or not ref.strip() for ref in artifact_refs)
                or len(artifact_refs) != len(set(artifact_refs))
            ):
                raise TypeError("Minecraft checkpoint observation identity is invalid")
            restored_last = Observation(
                observation_id=observation_id,
                generation=observation_generation,
                payload=last_raw["payload"],
                artifact_refs=tuple(artifact_refs),
            )
            if restored_last.generation != generation:
                raise ValueError("Minecraft checkpoint observation generation mismatch")
            expected_observation_id = (
                f"minecraft:{session_id}:observation:{observation_sequence}"
            )
            if restored_last.observation_id != expected_observation_id:
                raise ValueError("Minecraft checkpoint observation sequence mismatch")
        if (observation_sequence == 0) != (restored_last is None):
            raise ValueError("Minecraft checkpoint last observation cardinality mismatch")
        return MinecraftCheckpointSnapshot(
            world_payload=world_payload,
            observation_sequence=observation_sequence,
            actions=restored_actions,
            state=restored_state,
            last_observation=restored_last,
        )



__all__ = [
    "MinecraftActionResolution",
    "MinecraftSessionCheckpointPort",
    "MinecraftCheckpointCodec",
    "MinecraftCheckpointSnapshot",
]
