from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re

from noetrium_platform.foundation.kernel.kernel.errors import redact_text
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path

_SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
_BACKEND_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def process_environment_digest(environment: tuple[tuple[str, str], ...]) -> str:
    """Validate and identify one exact target-process environment without storing it elsewhere."""

    if tuple(sorted(environment)) != environment:
        raise ValueError("controller process environment must be sorted canonically")
    keys = tuple(key for key, _ in environment)
    if len(keys) != len(set(keys)):
        raise ValueError("controller process environment keys must be unique")
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not key
        or "=" in key
        or "\0" in key
        or "\0" in value
        for key, value in environment
    ):
        raise ValueError("controller process environment contains an unsafe entry")
    raw = json.dumps(environment, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class PersistentSessionReasonCode(StrEnum):
    EXACT = "exact"
    BINDING_MISSING = "binding_missing"
    BINDING_DRIFT = "binding_drift"
    TRANSPORT_IDENTITY_DRIFT = "transport_identity_drift"
    CONTROL_UNAVAILABLE = "control_unavailable"
    SESSION_MISSING = "session_missing"
    SESSION_IDENTITY_DRIFT = "session_identity_drift"
    CONTROLLER_NOT_LIVE = "controller_not_live"
    CONTROLLER_COMMAND_DRIFT = "controller_command_drift"
    CONTROLLER_CWD_DRIFT = "controller_cwd_drift"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"


class PersistentSessionDrift(RuntimeError):
    def __init__(self, code: PersistentSessionReasonCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class PersistentSessionEffectUncertain(RuntimeError):
    """An external create/terminate may have happened; caller must reconcile before retrying."""

    def __init__(
        self,
        operation: str,
        session_name: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        self.operation = operation
        self.session_name = session_name
        self.cause_type = type(cause).__qualname__ if cause is not None else None
        self.cause_message = redact_text(str(cause)) if cause is not None else None
        detail = ""
        if cause is not None:
            detail = f"; cause={self.cause_type}: {self.cause_message}"
        super().__init__(
            f"persistent-session {operation} effect certainty is unknown for {session_name}; reconcile required{detail}"
        )


@dataclass(frozen=True, slots=True)
class PersistentSessionSpec:
    """Frozen identity for a durable outer controller session.

    The session keeps only the outer controller reachable across operator/SSH
    disconnects. Service, process, checkpoint, experiment and scientific truth
    remain in their own authorities.
    """

    session_name: str
    command_argv: tuple[str, ...]
    cwd: str
    control_id: str
    runtime_manifest_digest: str
    command_identity_digest: str = ""
    process_environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not _SESSION_RE.fullmatch(self.session_name):
            raise ValueError("persistent session name must be a safe identifier")
        if not self.command_argv or not self.command_argv[0]:
            raise ValueError("persistent session command argv required")
        if not is_absolute_target_path(self.cwd):
            raise ValueError("persistent session cwd must be absolute")
        if not self.control_id:
            raise ValueError("persistent session control_id required")
        if len(self.runtime_manifest_digest) != 64:
            raise ValueError("runtime manifest digest must be SHA-256 hex")
        if self.command_identity_digest and len(self.command_identity_digest) != 64:
            raise ValueError("controller command identity must be SHA-256")
        process_environment_digest(self.process_environment)

    def digest(self) -> str:
        raw = json.dumps(
            asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistentSessionSnapshot:
    session_name: str
    exists: bool
    controller_pid: int | None = None
    controller_dead: bool | None = None
    start_command: str | None = None
    current_path: str | None = None
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PersistentSessionReport:
    spec_digest: str
    snapshot: PersistentSessionSnapshot
    attach_argv: tuple[str, ...]
    reused: bool
    evidence_refs: tuple[str, ...] = ()


class PersistentSessionObservationState(StrEnum):
    EXACT = "exact"
    MISSING = "missing"
    DRIFT = "drift"
    UNBOUND = "unbound"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PersistentSessionObservation:
    session_name: str
    state: PersistentSessionObservationState
    summary: str
    controller_pid: int | None = None
    evidence_refs: tuple[str, ...] = ()
    attach_argv: tuple[str, ...] = ()
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ServerSessionPolicy:
    backend_id: str
    transport_identity_digest: str
    release_layout: str = "content-addressed-release.v1"
    policy_version: str = "server-session-policy.v2"

    def __post_init__(self) -> None:
        if not _BACKEND_RE.fullmatch(self.backend_id):
            raise ValueError("server session backend_id must be a safe non-empty identifier")
        if len(self.transport_identity_digest) != 64:
            raise ValueError("server session transport identity must be SHA-256")
        if not self.release_layout or not self.policy_version:
            raise ValueError("server session policy identity required")

    def digest(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


__all__ = [
    "PersistentSessionDrift",
    "PersistentSessionReasonCode",
    "PersistentSessionEffectUncertain",
    "PersistentSessionObservation",
    "PersistentSessionObservationState",
    "PersistentSessionReport",
    "PersistentSessionSnapshot",
    "PersistentSessionSpec",
    "process_environment_digest",
    "ServerSessionPolicy",
]
