from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionIdentityViolation,
    ActionRequest,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput, canonical_bytes
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle


@dataclass(frozen=True, slots=True)
class MinecraftPreparedAction:
    action_type: str
    payload: JsonInput
    session_id: str
    generation: str
    provider_instance_id: str


class MinecraftActionRecoveryCodec:
    """Opaque recovery-handle codec; Reliability owns durability of the handle."""

    SCHEMA = "minecraft.action-recovery.v1"

    @classmethod
    def prepare(
        cls,
        request: ActionRequest,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
    ) -> PreparedEffectHandle:
        document = {
            "schema": cls.SCHEMA,
            "action_type": request.action_type,
            "payload": request.payload,
            "session_id": session_id,
            "generation": generation,
            "provider_instance_id": provider_instance_id,
        }
        return PreparedEffectHandle.build(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema=cls.SCHEMA,
            opaque_payload=canonical_bytes(document),
            provider_instance_id=provider_instance_id,
        )

    @classmethod
    def decode(
        cls,
        handle: PreparedEffectHandle,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
    ) -> MinecraftPreparedAction:
        if handle.provider_schema != cls.SCHEMA:
            raise ActionIdentityViolation("Minecraft prepared action provider schema mismatch")
        if handle.provider_instance_id != provider_instance_id:
            raise ActionIdentityViolation("Minecraft prepared action belongs to another provider instance")
        try:
            document = json.loads(handle.opaque_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActionIdentityViolation("Minecraft prepared action payload is invalid") from exc
        if not isinstance(document, Mapping) or set(document) != {
            "schema", "action_type", "payload", "session_id", "generation", "provider_instance_id"
        }:
            raise ActionIdentityViolation("Minecraft prepared action payload schema is invalid")
        if document.get("schema") != cls.SCHEMA:
            raise ActionIdentityViolation("Minecraft prepared action payload schema drift")
        if document.get("session_id") != session_id:
            raise ActionIdentityViolation("Minecraft prepared action session mismatch")
        if document.get("generation") != generation:
            raise ActionIdentityViolation("Minecraft prepared action environment generation mismatch")
        if document.get("provider_instance_id") != provider_instance_id:
            raise ActionIdentityViolation("Minecraft prepared action provider identity mismatch")
        action_type = document.get("action_type")
        if not isinstance(action_type, str) or not action_type.strip():
            raise ActionIdentityViolation("Minecraft prepared action type is invalid")
        return MinecraftPreparedAction(
            action_type=action_type,
            payload=document.get("payload"),
            session_id=session_id,
            generation=generation,
            provider_instance_id=provider_instance_id,
        )

    @classmethod
    def require_request(
        cls,
        request: ActionRequest,
        handle: PreparedEffectHandle,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
    ) -> MinecraftPreparedAction:
        prepared = cls.decode(
            handle,
            session_id=session_id,
            generation=generation,
            provider_instance_id=provider_instance_id,
        )
        if handle.request_id != request.action_id or handle.request_digest != action_request_digest(request):
            raise ActionIdentityViolation("Minecraft prepared action request identity mismatch")
        if (
            prepared.action_type != request.action_type
            or canonical_bytes(prepared.payload) != canonical_bytes(request.payload)
        ):
            raise ActionIdentityViolation("Minecraft prepared action request payload drift")
        return prepared


__all__ = ["MinecraftActionRecoveryCodec", "MinecraftPreparedAction"]
