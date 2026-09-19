from __future__ import annotations

"""Identity ledger for exactly-once Minecraft action submission."""

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionIdentityViolation,
    ActionRequest,
    action_request_digest,
)

from .checkpoint import MinecraftActionVerification


class MinecraftActionLedger:
    """Own action identity and verification state independently of session flow."""

    def __init__(
        self,
        values: Mapping[str, MinecraftActionVerification] | None = None,
    ) -> None:
        self._values = dict(values or {})

    def assert_new(self, request: ActionRequest) -> str:
        digest = action_request_digest(request)
        prior = self._values.get(request.action_id)
        if prior is None:
            return digest
        if prior.request_digest != digest:
            raise ActionIdentityViolation(
                f"Minecraft action identity was reused with drift: {request.action_id}"
            )
        raise ActionIdentityViolation(
            f"Minecraft action was already executed; reconcile its receipt: {request.action_id}"
        )

    def record(
        self,
        *,
        action_id: str,
        request_digest: str,
        accepted: bool,
        verified: bool | None,
    ) -> None:
        if not action_id.strip() or len(request_digest) != 64:
            raise ValueError("Minecraft action ledger identity is invalid")
        if action_id in self._values:
            raise ActionIdentityViolation(
                f"Minecraft action ledger already contains: {action_id}"
            )
        self._values[action_id] = MinecraftActionVerification(
            request_digest=request_digest,
            accepted=accepted,
            verified=verified,
        )

    def get(self, action_id: str) -> MinecraftActionVerification | None:
        return self._values.get(action_id)

    def snapshot(self) -> dict[str, MinecraftActionVerification]:
        return dict(self._values)

    def __len__(self) -> int:
        return len(self._values)


__all__ = ["MinecraftActionLedger"]
