from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionRequest,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput, canonical_bytes
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.substrate.api import (
    prepared_effect_handle,
    prepared_handle_field,
)


@dataclass(frozen=True, slots=True)
class MinecraftPreparedAction:
    action_type: str
    payload: JsonInput
    session_id: str
    generation: str
    provider_instance_id: str
    invocation_unit_digest: str
    authorization_unit_digest: str
    contract_validation: str
    rejection_code: str | None = None
    rejection_message: str | None = None


class MinecraftActionRecoveryCodec:
    """Opaque recovery-handle codec; Reliability owns durability of the handle."""

    SCHEMA = "minecraft.action-recovery.v3"

    @classmethod
    def prepare(
        cls,
        request: ActionRequest,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
        invocation_unit_digest: str,
        authorization_unit_digest: str,
        contract_validation: str,
        rejection_code: str | None = None,
        rejection_message: str | None = None,
    ) -> NoetriumUnit:
        for name, value in (
            ("invocation_unit_digest", invocation_unit_digest),
            ("authorization_unit_digest", authorization_unit_digest),
        ):
            if not isinstance(value, str) or len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"Minecraft prepared action {name} is invalid")
        if contract_validation not in {"not_reached", "passed", "failed"}:
            raise ValueError("Minecraft prepared action contract validation is invalid")
        if (rejection_code is None) != (rejection_message is None):
            raise ValueError("Minecraft prepared rejection requires code and message together")
        if rejection_code is not None and (
            not rejection_code.strip() or not rejection_message or not rejection_message.strip()
        ):
            raise ValueError("Minecraft prepared rejection must be non-empty")
        document = {
            "schema": cls.SCHEMA,
            "action_type": request.action_type,
            "payload": request.payload,
            "session_id": session_id,
            "generation": generation,
            "provider_instance_id": provider_instance_id,
            "invocation_unit_digest": invocation_unit_digest,
            "authorization_unit_digest": authorization_unit_digest,
            "contract_validation": contract_validation,
            "contract_rejection": (
                None
                if rejection_code is None
                else {"code": rejection_code, "message": rejection_message}
            ),
        }
        return prepared_effect_handle(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema=cls.SCHEMA,
            opaque_payload=canonical_bytes(document),
            provider_instance_id=provider_instance_id,
        )

    @classmethod
    def decode(
        cls,
        handle: NoetriumUnit,
        *,
        session_id: str,
        generation: str,
        provider_instance_id: str,
    ) -> MinecraftPreparedAction:
        if prepared_handle_field(handle, "provider_schema") != cls.SCHEMA:
            raise ActionIdentityViolation("Minecraft prepared action provider schema mismatch")
        if prepared_handle_field(handle, "provider_instance_id") != provider_instance_id:
            raise ActionIdentityViolation("Minecraft prepared action belongs to another provider instance")
        try:
            document = json.loads(prepared_handle_field(handle, "opaque_payload").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActionIdentityViolation("Minecraft prepared action payload is invalid") from exc
        if not isinstance(document, Mapping) or set(document) != {
            "schema", "action_type", "payload", "session_id", "generation",
            "provider_instance_id", "invocation_unit_digest",
            "authorization_unit_digest", "contract_validation",
            "contract_rejection"
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
        invocation_unit_digest = document.get("invocation_unit_digest")
        authorization_unit_digest = document.get("authorization_unit_digest")
        contract_validation = document.get("contract_validation")
        for name, value in (
            ("invocation_unit_digest", invocation_unit_digest),
            ("authorization_unit_digest", authorization_unit_digest),
        ):
            if not isinstance(value, str) or len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ActionIdentityViolation(
                    f"Minecraft prepared action {name} is invalid"
                )
        if contract_validation not in {"not_reached", "passed", "failed"}:
            raise ActionIdentityViolation(
                "Minecraft prepared action contract validation is invalid"
            )
        rejection = document.get("contract_rejection")
        rejection_code = None
        rejection_message = None
        if rejection is not None:
            if not isinstance(rejection, Mapping) or set(rejection) != {"code", "message"}:
                raise ActionIdentityViolation("Minecraft prepared rejection schema is invalid")
            raw_code = rejection.get("code")
            raw_message = rejection.get("message")
            if (
                not isinstance(raw_code, str)
                or not raw_code.strip()
                or not isinstance(raw_message, str)
                or not raw_message.strip()
            ):
                raise ActionIdentityViolation("Minecraft prepared rejection is invalid")
            rejection_code = raw_code.strip()
            rejection_message = raw_message.strip()
        return MinecraftPreparedAction(
            action_type=action_type,
            payload=document.get("payload"),
            session_id=session_id,
            generation=generation,
            provider_instance_id=provider_instance_id,
            invocation_unit_digest=invocation_unit_digest,
            authorization_unit_digest=authorization_unit_digest,
            contract_validation=contract_validation,
            rejection_code=rejection_code,
            rejection_message=rejection_message,
        )

    @classmethod
    def require_request(
        cls,
        request: ActionRequest,
        handle: NoetriumUnit,
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
        if prepared_handle_field(handle, "request_id") != request.action_id or prepared_handle_field(handle, "request_digest") != action_request_digest(request):
            raise ActionIdentityViolation("Minecraft prepared action request identity mismatch")
        if (
            prepared.action_type != request.action_type
            or canonical_bytes(prepared.payload) != canonical_bytes(request.payload)
        ):
            raise ActionIdentityViolation("Minecraft prepared action request payload drift")
        from ..api import minecraft_action_invocation_unit
        if (
            minecraft_action_invocation_unit(request).unit_digest
            != prepared.invocation_unit_digest
        ):
            raise ActionIdentityViolation(
                "Minecraft prepared action invocation Unit identity drift"
            )
        return prepared


__all__ = ["MinecraftActionRecoveryCodec", "MinecraftPreparedAction"]
