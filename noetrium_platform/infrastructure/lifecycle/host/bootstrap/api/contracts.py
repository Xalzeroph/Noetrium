from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import time

from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionReport


class ServerBootstrapPhase(StrEnum):
    PLANNED = "planned"
    RELEASE_PINNED = "release_pinned"
    CONTROLLER_EFFECT_PENDING = "controller_effect_pending"
    RECONCILE_REQUIRED = "reconcile_required"
    COMMITTED = "committed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ServerBootstrapState:
    control_id: str
    runtime_manifest_digest: str
    release_digest: str
    session_spec_digest: str
    session_policy_digest: str
    phase: ServerBootstrapPhase
    revision: int
    evidence_refs: tuple[str, ...]
    last_error_type: str | None
    last_error_digest: str | None
    updated_at: float

    def __post_init__(self) -> None:
        if not self.control_id:
            raise ValueError("server bootstrap control_id required")
        for value in (
            self.runtime_manifest_digest,
            self.release_digest,
            self.session_spec_digest,
            self.session_policy_digest,
        ):
            if len(value) != 64:
                raise ValueError("server bootstrap identities must be SHA-256")
        if self.revision < 0:
            raise ValueError("server bootstrap revision must be non-negative")
        if self.updated_at <= 0:
            raise ValueError("server bootstrap timestamp required")

    @classmethod
    def create(
        cls,
        *,
        control_id: str,
        runtime_manifest_digest: str,
        release_digest: str,
        session_spec_digest: str,
        session_policy_digest: str,
    ) -> "ServerBootstrapState":
        return cls(
            control_id,
            runtime_manifest_digest,
            release_digest,
            session_spec_digest,
            session_policy_digest,
            ServerBootstrapPhase.PLANNED,
            0,
            (),
            None,
            None,
            time.time(),
        )

    def same_identity(self, other: "ServerBootstrapState") -> bool:
        return (
            self.control_id,
            self.runtime_manifest_digest,
            self.release_digest,
            self.session_spec_digest,
            self.session_policy_digest,
        ) == (
            other.control_id,
            other.runtime_manifest_digest,
            other.release_digest,
            other.session_spec_digest,
            other.session_policy_digest,
        )


class ServerBootstrapIdentityConflict(RuntimeError):
    pass


class ServerBootstrapStateConflict(RuntimeError):
    pass


class ServerBootstrapBlocked(RuntimeError):
    """A prior bootstrap attempt established a fail-closed identity/drift condition."""


@dataclass(frozen=True, slots=True)
class ServerBootstrapTransactionReport:
    state: ServerBootstrapState
    session: PersistentSessionReport


__all__ = [
    "ServerBootstrapBlocked",
    "ServerBootstrapIdentityConflict",
    "ServerBootstrapPhase",
    "ServerBootstrapState",
    "ServerBootstrapStateConflict",
    "ServerBootstrapTransactionReport",
]
