from __future__ import annotations

import math
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.infrastructure.resources.authority import lease_field
from noetrium_platform.infrastructure.reliability.recovery.api.lease import (
    RecoveryLease,
    RecoveryLeaseBusy,
)
from noetrium_platform.infrastructure.reliability.recovery.api import (
    RecoveryLeaseStatePort,
)


_RECOVERY_RESOURCE_KEY = "recovery:runtime"


def _lease_id(owner_id: str, manifest_digest: str) -> str:
    return "recovery:" + canonical_digest(
        {
            "owner_id": owner_id,
            "manifest_digest": manifest_digest,
        }
    )


class RecoveryLeaseProjection:
    """Recovery-specific projection over UniversalResourceAuthority."""

    def __init__(
        self,
        authority: UniversalResourceAuthority,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(authority, UniversalResourceAuthority):
            raise TypeError(
                "recovery lease projection requires UniversalResourceAuthority"
            )
        self._authority = authority
        self._evidence_refs = tuple(evidence_refs)

    @staticmethod
    def _validate_time(
        ttl_seconds: float,
        now: float | None,
    ) -> float | None:
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        if now is None:
            return None
        observed = float(now)
        if not math.isfinite(observed) or observed <= 0:
            raise ValueError(
                "recovery lease observation time must be finite and positive"
            )
        return observed

    @staticmethod
    def _project(lease: NoetriumUnit) -> RecoveryLease:
        metadata = dict(lease_field(lease, "metadata") or {})
        owner_id = metadata.get("owner_id")
        manifest_digest = metadata.get("manifest_digest")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise RuntimeError("recovery lease owner projection is invalid")
        if (
            not isinstance(manifest_digest, str)
            or not manifest_digest.strip()
        ):
            raise RuntimeError(
                "recovery lease manifest projection is invalid"
            )
        if (
            lease_field(lease, "acquired_at_epoch_s") is None
            or lease_field(lease, "expires_at_epoch_s") is None
        ):
            raise RuntimeError(
                "recovery Authority lease lacks acquisition/expiry evidence"
            )
        return RecoveryLease(
            owner_id,
            manifest_digest,
            lease_field(lease, "acquired_at_epoch_s"),
            lease_field(lease, "expires_at_epoch_s"),
        )

    def _active(self, *, now: float | None = None) -> NoetriumUnit | None:
        rows = self._authority.active_leases(
            _RECOVERY_RESOURCE_KEY,
            now=now,
        )
        if len(rows) > 1:
            raise RuntimeError(
                "exclusive recovery resource has multiple live leases"
            )
        return None if not rows else rows[0]

    def read(self, *, now: float | None = None) -> RecoveryLease | None:
        current = self._active(now=now)
        return None if current is None else self._project(current)

    def evidence_refs(self) -> tuple[str, ...]:
        return self._evidence_refs or (
            "universal-resource-authority:recovery:runtime",
        )

    def acquire(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> RecoveryLease:
        if not owner_id.strip() or not manifest_digest.strip():
            raise ValueError(
                "recovery lease owner and manifest identity are required"
            )
        observed = self._validate_time(ttl_seconds, now)
        try:
            lease = self._authority.acquire_exclusive_ttl_lease(
                lease_id=_lease_id(owner_id, manifest_digest),
                resource_key=_RECOVERY_RESOURCE_KEY,
                holder_key=owner_id,
                owner_scope=PLATFORM_SCOPE,
                ttl_seconds=ttl_seconds,
                now=observed,
                metadata={
                    "kind": "recovery",
                    "owner_id": owner_id,
                    "manifest_digest": manifest_digest,
                },
            )
        except RuntimeError as exc:
            raise RecoveryLeaseBusy(
                "runtime recovery lease is held by another owner/manifest"
            ) from exc
        return self._project(lease)

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
            raise RecoveryLeaseBusy(
                "runtime recovery lease cannot be renewed"
            )
        projected = self._project(current)
        if (
            projected.owner_id != owner_id
            or projected.manifest_digest != manifest_digest
        ):
            raise RecoveryLeaseBusy(
                "runtime recovery lease cannot be renewed by this owner/manifest"
            )
        try:
            renewed = self._authority.renew_lease(
                current,
                ttl_seconds=ttl_seconds,
                now=observed,
            )
        except (KeyError, RuntimeError) as exc:
            raise RecoveryLeaseBusy(
                "runtime recovery lease renewal lost authority"
            ) from exc
        return self._project(renewed)

    def assert_owned(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        now: float | None = None,
    ) -> RecoveryLease:
        observed = None if now is None else float(now)
        if observed is not None and (
            not math.isfinite(observed) or observed <= 0
        ):
            raise ValueError(
                "recovery lease observation time must be finite and positive"
            )
        current = self._active(now=observed)
        if current is None:
            raise RecoveryLeaseBusy("runtime recovery lease not held")
        projected = self._project(current)
        if (
            projected.owner_id != owner_id
            or projected.manifest_digest != manifest_digest
        ):
            raise RecoveryLeaseBusy("runtime recovery lease not held")
        return projected

    def release(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        now: float | None = None,
    ) -> None:
        current = self._active(now=now)
        if current is None:
            return
        projected = self._project(current)
        if (
            projected.owner_id != owner_id
            or projected.manifest_digest != manifest_digest
        ):
            raise RecoveryLeaseBusy(
                "cannot release runtime recovery lease owned by a different "
                "owner/manifest"
            )
        try:
            self._authority.release_lease(current)
            generation = self._authority.generation(_RECOVERY_RESOURCE_KEY)
            if (
                generation is not None
                and generation.generation == int(lease_field(current, "generation"))
            ):
                self._authority.advance_generation(_RECOVERY_RESOURCE_KEY)
        except (KeyError, RuntimeError) as exc:
            raise RecoveryLeaseBusy(
                "runtime recovery lease release lost authority"
            ) from exc


def compose_sqlite_recovery_lease(
    database: str | Path,
) -> RecoveryLeaseStatePort:
    path = Path(database)
    return RecoveryLeaseProjection(
        UniversalResourceAuthority(path),
        evidence_refs=(
            f"universal-resource-authority:{path.absolute()}",
        ),
    )


def compose_resource_recovery_lease(
    authority: UniversalResourceAuthority,
    *,
    evidence_refs: tuple[str, ...] = (),
) -> RecoveryLeaseStatePort:
    return RecoveryLeaseProjection(
        authority,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "RecoveryLeaseProjection",
    "compose_resource_recovery_lease",
    "compose_sqlite_recovery_lease",
]
