from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    JsonValue,
    canonical_bytes,
    canonical_digest,
)

from ..api import (
    ActionResult,
    Observation,
    freeze_json_mapping,
    thaw_json_mapping,
)


class StateMachineCheckpointError(ValueError):
    """A state-machine checkpoint is malformed or belongs to another session."""


@dataclass(frozen=True, slots=True)
class AppliedStateMachineAction:
    request_digest: str
    result: ActionResult


@dataclass(frozen=True, slots=True)
class DecodedStateMachineCheckpoint:
    state: Mapping[str, JsonValue]
    observation_sequence: int
    actions: tuple[tuple[str, AppliedStateMachineAction], ...]


class StateMachineCheckpointCodec:
    SCHEMA = "environment.state-machine.session.v1"

    def __init__(
        self,
        *,
        session_id: str,
        environment_generation: str,
        provider_instance_id: str,
    ) -> None:
        self.session_id = session_id
        self.environment_generation = environment_generation
        self.provider_instance_id = provider_instance_id

    @staticmethod
    def _effect_document(effect: EffectReceipt) -> dict[str, object]:
        return {
            "effect_id": effect.effect_id,
            "request_digest": effect.request_digest,
            "effect_class": effect.effect_class.value,
            "certainty": effect.certainty.value,
            "provider_instance_id": effect.provider_instance_id,
            "verification_required": effect.verification_required,
            "before_artifact": effect.before_artifact,
            "after_artifact": effect.after_artifact,
            "provider_receipt": effect.provider_receipt,
        }

    @classmethod
    def _result_document(cls, result: ActionResult) -> dict[str, object]:
        observation = result.observation
        effect = result.effect
        return {
            "action_id": result.action_id,
            "accepted": result.accepted,
            "observation": None
            if observation is None
            else {
                "observation_id": observation.observation_id,
                "generation": observation.generation,
                "payload": observation.payload,
                "artifact_refs": observation.artifact_refs,
            },
            "effect": None if effect is None else cls._effect_document(effect),
            "diagnostics": result.diagnostics,
        }

    def encode(
        self,
        *,
        state: Mapping[str, JsonValue],
        observation_sequence: int,
        actions: Mapping[str, AppliedStateMachineAction],
    ) -> bytes:
        state_document = thaw_json_mapping(state)
        return canonical_bytes(
            {
                "schema_version": self.SCHEMA,
                "session_id": self.session_id,
                "environment_generation": self.environment_generation,
                "state": state_document,
                "state_digest": canonical_digest(state_document),
                "observation_sequence": observation_sequence,
                "actions": [
                    {
                        "action_id": action_id,
                        "request_digest": applied.request_digest,
                        "result": self._result_document(applied.result),
                    }
                    for action_id, applied in actions.items()
                ],
            }
        )

    def _decode_result(self, document: Mapping[str, JsonValue]) -> ActionResult:
        expected_fields = {
            "action_id",
            "accepted",
            "observation",
            "effect",
            "diagnostics",
        }
        if set(document) != expected_fields:
            raise StateMachineCheckpointError("checkpoint result schema is malformed")
        action_id = document["action_id"]
        accepted = document["accepted"]
        if (
            not isinstance(action_id, str)
            or not action_id.strip()
            or not isinstance(accepted, bool)
        ):
            raise StateMachineCheckpointError("checkpoint result identity is malformed")
        observation_raw = document.get("observation")
        effect_raw = document.get("effect")
        observation = None
        if observation_raw is not None:
            if not isinstance(observation_raw, Mapping):
                raise StateMachineCheckpointError("checkpoint observation is malformed")
            if set(observation_raw) != {
                "observation_id",
                "generation",
                "payload",
                "artifact_refs",
            }:
                raise StateMachineCheckpointError(
                    "checkpoint observation schema is malformed"
                )
            if not isinstance(observation_raw["payload"], Mapping):
                raise StateMachineCheckpointError(
                    "checkpoint observation payload is malformed"
                )
            artifact_refs_raw = observation_raw["artifact_refs"]
            if (
                not isinstance(artifact_refs_raw, (list, tuple))
                or any(
                    not isinstance(ref, str) or not ref.strip()
                    for ref in artifact_refs_raw
                )
                or len(artifact_refs_raw) != len(set(artifact_refs_raw))
            ):
                raise StateMachineCheckpointError(
                    "checkpoint observation artifacts are malformed"
                )
            observation = Observation(
                observation_id=observation_raw["observation_id"],
                generation=observation_raw["generation"],
                payload=thaw_json_mapping(
                    freeze_json_mapping(
                        observation_raw["payload"],
                        field="checkpoint.observation.payload",
                    )
                ),
                artifact_refs=tuple(artifact_refs_raw),
            )
            if (
                not isinstance(observation.observation_id, str)
                or not observation.observation_id.strip()
                or not isinstance(observation.generation, str)
            ):
                raise StateMachineCheckpointError(
                    "checkpoint observation identity is malformed"
                )
            if observation.generation != self.environment_generation:
                raise StateMachineCheckpointError(
                    "checkpoint observation generation drift"
                )
        effect = None
        if effect_raw is not None:
            if not isinstance(effect_raw, Mapping):
                raise StateMachineCheckpointError("checkpoint effect is malformed")
            if set(effect_raw) != {
                "effect_id",
                "request_digest",
                "effect_class",
                "certainty",
                "provider_instance_id",
                "verification_required",
                "before_artifact",
                "after_artifact",
                "provider_receipt",
            }:
                raise StateMachineCheckpointError(
                    "checkpoint effect schema is malformed"
                )
            if not isinstance(effect_raw["verification_required"], bool):
                raise StateMachineCheckpointError(
                    "checkpoint effect verification is malformed"
                )
            required_effect_strings = (
                "effect_id",
                "request_digest",
                "effect_class",
                "certainty",
                "provider_instance_id",
                "after_artifact",
                "provider_receipt",
            )
            if any(
                not isinstance(effect_raw[name], str)
                or not effect_raw[name].strip()
                for name in required_effect_strings
            ):
                raise StateMachineCheckpointError(
                    "checkpoint effect identity is malformed"
                )
            before_artifact = effect_raw["before_artifact"]
            if before_artifact is not None and (
                not isinstance(before_artifact, str)
                or not before_artifact.strip()
            ):
                raise StateMachineCheckpointError(
                    "checkpoint effect before artifact is malformed"
                )
            effect = EffectReceipt(
                effect_id=effect_raw["effect_id"],
                request_digest=effect_raw["request_digest"],
                effect_class=EffectClass(str(effect_raw["effect_class"])),
                certainty=EffectCertainty(str(effect_raw["certainty"])),
                provider_instance_id=(
                    None
                    if effect_raw.get("provider_instance_id") is None
                    else effect_raw["provider_instance_id"]
                ),
                verification_required=effect_raw["verification_required"],
                before_artifact=(
                    None
                    if effect_raw.get("before_artifact") is None
                    else effect_raw["before_artifact"]
                ),
                after_artifact=(
                    None
                    if effect_raw.get("after_artifact") is None
                    else effect_raw["after_artifact"]
                ),
                provider_receipt=(
                    None
                    if effect_raw.get("provider_receipt") is None
                    else effect_raw["provider_receipt"]
                ),
            )
            if effect.provider_instance_id != self.provider_instance_id:
                raise StateMachineCheckpointError(
                    "checkpoint effect provider drift"
                )
            if effect.effect_id != f"state-machine-action:{action_id}":
                raise StateMachineCheckpointError(
                    "checkpoint effect identity drift"
                )
            if effect.provider_receipt != action_id:
                raise StateMachineCheckpointError(
                    "checkpoint effect receipt drift"
                )
            if (
                effect.effect_class is not EffectClass.IDEMPOTENT
                or effect.verification_required
            ):
                raise StateMachineCheckpointError(
                    "checkpoint effect contract drift"
                )
            if (
                len(effect.request_digest) != 64
                or effect.request_digest != effect.request_digest.lower()
                or any(
                    char not in "0123456789abcdef"
                    for char in effect.request_digest
                )
            ):
                raise StateMachineCheckpointError(
                    "checkpoint effect request digest is malformed"
                )
            if (
                effect.after_artifact is None
                or len(effect.after_artifact) != 64
                or effect.after_artifact != effect.after_artifact.lower()
                or any(
                    char not in "0123456789abcdef"
                    for char in effect.after_artifact
                )
            ):
                raise StateMachineCheckpointError(
                    "checkpoint effect state digest is malformed"
                )
            expected_certainty = (
                EffectCertainty.EFFECT_CONFIRMED
                if accepted
                else EffectCertainty.EFFECT_REJECTED
            )
            if effect.certainty is not expected_certainty:
                raise StateMachineCheckpointError(
                    "checkpoint effect certainty drift"
                )
        diagnostics = document.get("diagnostics", {})
        if not isinstance(diagnostics, Mapping):
            raise StateMachineCheckpointError(
                "checkpoint result diagnostics are malformed"
            )
        restored_diagnostics = thaw_json_mapping(
            freeze_json_mapping(
                diagnostics,
                field="checkpoint.result.diagnostics",
            )
        )
        return ActionResult(
            action_id=action_id,
            accepted=accepted,
            observation=observation,
            effect=effect,
            diagnostics=restored_diagnostics,
        )

    def decode(self, payload: bytes) -> DecodedStateMachineCheckpoint:
        try:
            raw = json.loads(payload.decode("utf-8"))
            if not isinstance(raw, Mapping):
                raise TypeError("checkpoint root must be a mapping")
            if set(raw) != {
                "schema_version",
                "session_id",
                "environment_generation",
                "state",
                "state_digest",
                "observation_sequence",
                "actions",
            }:
                raise ValueError("checkpoint root schema mismatch")
            if raw["schema_version"] != self.SCHEMA:
                raise ValueError("unsupported checkpoint schema")
            if raw["session_id"] != self.session_id:
                raise ValueError("checkpoint session identity mismatch")
            if raw["environment_generation"] != self.environment_generation:
                raise ValueError("checkpoint environment generation mismatch")
            state_raw = raw["state"]
            if not isinstance(state_raw, Mapping):
                raise TypeError("checkpoint state must be a mapping")
            state = freeze_json_mapping(
                state_raw,
                field="checkpoint.state",
            )
            state_digest = canonical_digest(state)
            if raw["state_digest"] != state_digest:
                raise ValueError("checkpoint state digest mismatch")
            sequence = raw["observation_sequence"]
            if (
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 0
            ):
                raise ValueError("checkpoint observation sequence is negative")
            action_rows = raw["actions"]
            if not isinstance(action_rows, list):
                raise TypeError("checkpoint actions must be a list")
            actions: dict[str, AppliedStateMachineAction] = {}
            observation_ids: set[str] = set()
            prefix = f"state-machine:{self.session_id}:observation:"
            last_effect: EffectReceipt | None = None
            for row in action_rows:
                if (
                    not isinstance(row, Mapping)
                    or not isinstance(row.get("result"), Mapping)
                ):
                    raise TypeError("checkpoint action row is malformed")
                if set(row) != {"action_id", "request_digest", "result"}:
                    raise ValueError("checkpoint action row schema mismatch")
                action_id = row["action_id"]
                request_digest = row["request_digest"]
                if (
                    not isinstance(action_id, str)
                    or not action_id.strip()
                    or not isinstance(request_digest, str)
                    or len(request_digest) != 64
                    or request_digest != request_digest.lower()
                    or any(
                        char not in "0123456789abcdef"
                        for char in request_digest
                    )
                    or action_id in actions
                ):
                    raise ValueError("checkpoint action identity is invalid")
                result = self._decode_result(row["result"])
                if result.action_id != action_id:
                    raise ValueError(
                        "checkpoint action/result identity mismatch"
                    )
                effect = result.effect
                if effect is None or effect.request_digest != request_digest:
                    raise ValueError(
                        "checkpoint action/effect digest mismatch"
                    )
                if effect.provider_receipt != action_id:
                    raise ValueError(
                        "checkpoint action/effect receipt mismatch"
                    )
                observation = result.observation
                if observation is None:
                    raise ValueError(
                        "checkpoint action observations are incomplete"
                    )
                observation_id = observation.observation_id
                if observation_id in observation_ids:
                    raise ValueError(
                        "checkpoint action observations are duplicated"
                    )
                observation_ids.add(observation_id)
                if not observation_id.startswith(prefix):
                    raise ValueError(
                        "checkpoint action observation identity drift"
                    )
                try:
                    observation_number = int(observation_id[len(prefix) :])
                except ValueError as exc:
                    raise ValueError(
                        "checkpoint action observation sequence is invalid"
                    ) from exc
                if observation_number < 1 or observation_number > sequence:
                    raise ValueError(
                        "checkpoint action observation sequence is invalid"
                    )
                actions[action_id] = AppliedStateMachineAction(
                    request_digest,
                    result,
                )
                last_effect = effect
            if sequence < len(actions):
                raise ValueError(
                    "checkpoint observation sequence precedes action ledger"
                )
            if (
                last_effect is not None
                and last_effect.after_artifact != state_digest
            ):
                raise ValueError(
                    "checkpoint final state does not match the action ledger"
                )
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            if isinstance(exc, StateMachineCheckpointError):
                raise
            raise StateMachineCheckpointError(
                "invalid or incompatible state-machine checkpoint"
            ) from exc
        return DecodedStateMachineCheckpoint(
            state=state,
            observation_sequence=sequence,
            actions=tuple(actions.items()),
        )


__all__ = [
    "AppliedStateMachineAction",
    "DecodedStateMachineCheckpoint",
    "StateMachineCheckpointCodec",
    "StateMachineCheckpointError",
]
