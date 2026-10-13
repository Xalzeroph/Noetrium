from __future__ import annotations

"""Identity ledger for exactly-once Minecraft action submission."""

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionRequest,
    action_request_digest,
)

from .checkpoint import MinecraftActionResolution


class MinecraftActionLedger:
    """Own action identity and verification state independently of session flow."""

    def __init__(
        self,
        values: Mapping[str, MinecraftActionResolution] | None = None,
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

    @staticmethod
    def _validate_resolution(
        action_id: str,
        request_digest: str,
        disposition: ActionReconciliationDisposition,
        invocation_unit_digest: str | None,
        authorization_unit_digest: str | None,
    ) -> None:
        if not action_id.strip() or len(request_digest) != 64:
            raise ValueError("Minecraft action ledger identity is invalid")
        if not isinstance(disposition, ActionReconciliationDisposition):
            raise TypeError("Minecraft action disposition is invalid")
        if (invocation_unit_digest is None) != (authorization_unit_digest is None):
            raise ValueError("Minecraft action ledger Unit lineage must be complete")
        for value in (invocation_unit_digest, authorization_unit_digest):
            if value is not None and (
                len(value) != 64
                or value != value.lower()
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError("Minecraft action ledger Unit digest is invalid")

    def record(
        self,
        *,
        action_id: str,
        request_digest: str,
        disposition: ActionReconciliationDisposition,
        invocation_unit_digest: str | None = None,
        authorization_unit_digest: str | None = None,
    ) -> None:
        self._validate_resolution(
            action_id, request_digest, disposition,
            invocation_unit_digest, authorization_unit_digest,
        )
        if action_id in self._values:
            raise ActionIdentityViolation(
                f"Minecraft action ledger already contains: {action_id}"
            )
        self._values[action_id] = MinecraftActionResolution(
            request_digest=request_digest,
            disposition=disposition,
            invocation_unit_digest=invocation_unit_digest,
            authorization_unit_digest=authorization_unit_digest,
        )

    def resolve(
        self,
        *,
        action_id: str,
        request_digest: str,
        disposition: ActionReconciliationDisposition,
        invocation_unit_digest: str | None = None,
        authorization_unit_digest: str | None = None,
    ) -> None:
        """Monotonically refine one action identity from UNKNOWN to terminal truth.

        UNKNOWN fences replay after delivery uncertainty. Reconciliation may
        later replace only that uncertainty with a terminal provider proof. A
        terminal fact is immutable; an inconsistent later proof is an identity
        violation rather than a last-writer-wins update.
        """
        self._validate_resolution(
            action_id, request_digest, disposition,
            invocation_unit_digest, authorization_unit_digest,
        )
        prior = self._values.get(action_id)
        if prior is None:
            self._values[action_id] = MinecraftActionResolution(
                request_digest=request_digest,
                disposition=disposition,
                invocation_unit_digest=invocation_unit_digest,
                authorization_unit_digest=authorization_unit_digest,
            )
            return
        if prior.request_digest != request_digest:
            raise ActionIdentityViolation(
                f"Minecraft action resolution identity drift: {action_id}"
            )
        if invocation_unit_digest is not None and (
            prior.invocation_unit_digest != invocation_unit_digest
            or prior.authorization_unit_digest != authorization_unit_digest
        ):
            raise ActionIdentityViolation(
                f"Minecraft action Unit lineage drift: {action_id}"
            )
        if prior.disposition is disposition:
            return
        if prior.disposition is not ActionReconciliationDisposition.UNKNOWN:
            raise ActionIdentityViolation(
                f"Minecraft terminal action resolution cannot be rewritten: {action_id}"
            )
        self._values[action_id] = MinecraftActionResolution(
            request_digest=request_digest,
            disposition=disposition,
            invocation_unit_digest=(
                prior.invocation_unit_digest
                if invocation_unit_digest is None else invocation_unit_digest
            ),
            authorization_unit_digest=(
                prior.authorization_unit_digest
                if authorization_unit_digest is None else authorization_unit_digest
            ),
        )

    def get(self, action_id: str) -> MinecraftActionResolution | None:
        return self._values.get(action_id)

    def snapshot(self) -> dict[str, MinecraftActionResolution]:
        return dict(self._values)

    def __len__(self) -> int:
        return len(self._values)


__all__ = ["MinecraftActionLedger"]
