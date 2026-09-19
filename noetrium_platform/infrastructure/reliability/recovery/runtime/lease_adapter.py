from __future__ import annotations

import json
import math
from time import time

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseConflict,
    ResourceLeaseExpired,
    ResourceLeasePort,
    ResourceOwner,
    ResourceOwnership,
    ResourceOwnershipPort,
)

from ..api.lease import RecoveryLease, RecoveryLeaseBusy


_RECOVERY_RESOURCE = ResourceIdentity(ResourceKind.RECOVERY, "runtime")


def _purpose(owner_id: str, manifest_digest: str) -> str:
    return json.dumps(
        {"manifest_digest": manifest_digest, "owner_id": owner_id},
        sort_keys=True,
        separators=(",", ":"),
    )


def _parse_purpose(value: str) -> tuple[str, str]:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("recovery lease purpose is corrupt") from exc
    if not isinstance(document, dict) or set(document) != {"manifest_digest", "owner_id"}:
        raise RuntimeError("recovery lease purpose fields are invalid")
    owner_id = document["owner_id"]
    manifest_digest = document["manifest_digest"]
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise RuntimeError("recovery lease owner projection is invalid")
    if not isinstance(manifest_digest, str) or not manifest_digest.strip():
        raise RuntimeError("recovery lease manifest projection is invalid")
    return owner_id, manifest_digest


def _lease_id(owner_id: str, manifest_digest: str) -> str:
    return "recovery:" + canonical_digest({
        "owner_id": owner_id,
        "manifest_digest": manifest_digest,
    })


class RecoveryLeaseAdapter:
    """Recovery-specific view over the canonical resource lease authority."""

    def __init__(
        self,
        ownership: ResourceOwnershipPort,
        leases: ResourceLeasePort,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        self._ownership = ownership
        self._leases = leases
        self._evidence_refs = tuple(evidence_refs)
        self._ownership.register_owner(
            ResourceOwner(
                _RECOVERY_RESOURCE,
                PLATFORM_SCOPE,
                ResourceOwnership.PLATFORM_MANAGED,
            )
        )
    @staticmethod
    def _validate_time(ttl_seconds: float, now: float | None) -> float:
        if not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        observed = time() if now is None else float(now)
        if not math.isfinite(observed):
            raise ValueError("recovery lease observation time must be finite")
        return observed

    @staticmethod
    def _project(lease: ResourceLease) -> RecoveryLease:
        owner_id, manifest_digest = _parse_purpose(lease.purpose)
        if lease.acquired_at_epoch_s is None or lease.expires_at_epoch_s is None:
            raise RuntimeError("recovery resource lease lacks acquisition/expiry evidence")
        return RecoveryLease(
            owner_id,
            manifest_digest,
            lease.acquired_at_epoch_s,
            lease.expires_at_epoch_s,
        )

    def _active(self, *, now: float | None = None) -> ResourceLease | None:
        rows = self._leases.active_for(_RECOVERY_RESOURCE, now=now)
        if len(rows) > 1:
            raise RuntimeError("recovery resource has multiple active leases")
        return None if not rows else rows[0]

    def _latest(self, *, now: float | None = None) -> ResourceLease | None:
        rows = self._leases.history_for(_RECOVERY_RESOURCE, now=now)
        return None if not rows else rows[-1]

    def read(self) -> RecoveryLease | None:
        current = self._latest()
        if current is None or current.state is LeaseState.RELEASED:
            return None
        return self._project(current)

    def evidence_refs(self) -> tuple[str, ...]:
        return self._evidence_refs or ("resource-lease:recovery:runtime",)
    def acquire(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> RecoveryLease:
        if not owner_id.strip() or not manifest_digest.strip():
            raise ValueError("recovery lease owner and manifest identity are required")
        observed = self._validate_time(ttl_seconds, now)
        current = self._active(now=observed)
        if current is not None:
            projected = self._project(current)
            if projected.owner_id != owner_id or projected.manifest_digest != manifest_digest:
                raise RecoveryLeaseBusy(
                    "runtime recovery lease held by a different owner/manifest"
                )
            try:
                renewed = self._leases.renew(
                    current.lease_id,
                    fencing_token=current.fencing_token,
                    ttl_seconds=ttl_seconds,
                    now=observed,
                )
            except (ResourceLeaseConflict, ResourceLeaseExpired) as exc:
                raise RecoveryLeaseBusy("runtime recovery lease renewal lost authority") from exc
            return self._project(renewed)
        requested = ResourceLease(
            _lease_id(owner_id, manifest_digest),
            _RECOVERY_RESOURCE,
            PLATFORM_SCOPE,
            _purpose(owner_id, manifest_digest),
        )
        try:
            granted = self._leases.acquire(
                requested,
                ttl_seconds=ttl_seconds,
                now=observed,
            )
        except ResourceLeaseConflict as exc:
            raise RecoveryLeaseBusy("runtime recovery lease is already held") from exc
        return self._project(granted)
    def renew(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> RecoveryLease:
        observed = self._validate_time(ttl_seconds, now)
        current = self._active(now=observed)
        if current is None:
            raise RecoveryLeaseBusy("runtime recovery lease cannot be renewed")
        projected = self._project(current)
        if projected.owner_id != owner_id or projected.manifest_digest != manifest_digest:
            raise RecoveryLeaseBusy("runtime recovery lease cannot be renewed by this owner/manifest")
        try:
            renewed = self._leases.renew(
                current.lease_id,
                fencing_token=current.fencing_token,
                ttl_seconds=ttl_seconds,
                now=observed,
            )
        except (ResourceLeaseConflict, ResourceLeaseExpired) as exc:
            raise RecoveryLeaseBusy("runtime recovery lease renewal lost authority") from exc
        return self._project(renewed)

    def assert_owned(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        now: float | None = None,
    ) -> RecoveryLease:
        observed = time() if now is None else float(now)
        if not math.isfinite(observed):
            raise ValueError("recovery lease observation time must be finite")
        current = self._active(now=observed)
        if current is None:
            raise RecoveryLeaseBusy("runtime recovery lease not held")
        projected = self._project(current)
        if projected.owner_id != owner_id or projected.manifest_digest != manifest_digest:
            raise RecoveryLeaseBusy("runtime recovery lease not held")
        return projected
    def release(self, owner_id: str, manifest_digest: str) -> None:
        current = self._latest()
        if current is None:
            return
        projected = self._project(current)
        if projected.owner_id != owner_id or projected.manifest_digest != manifest_digest:
            raise RecoveryLeaseBusy(
                "cannot release runtime recovery lease owned by a different owner/manifest"
            )
        try:
            self._leases.release(current.lease_id)
        except (ResourceLeaseConflict, ResourceLeaseExpired) as exc:
            raise RecoveryLeaseBusy("runtime recovery lease release lost authority") from exc


__all__ = ["RecoveryLeaseAdapter"]
