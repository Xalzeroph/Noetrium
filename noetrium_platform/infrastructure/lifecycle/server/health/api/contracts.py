from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import posixpath

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationRecord


def _absolute(value: str, field: str) -> str:
    if not posixpath.isabs(value) or posixpath.normpath(value) == "/":
        raise ValueError(f"{field} must be an absolute non-root POSIX path")
    return posixpath.normpath(value)


@dataclass(frozen=True, slots=True)
class ServerRuntimeHealthSpec:
    """Exact remote paths and identities required by one platform deployment."""

    platform_root: str
    release_root: str
    repository_root: str
    remote_home: str
    python_executable: str
    python_binary_sha256: str
    python_packages_sha256: str
    node_executable: str
    node_binary_sha256: str
    java_executable: str
    java_binary_sha256: str
    platform_management_executable: str
    platform_management_binary_sha256: str
    tmux_executable: str
    sha256sum_executable: str
    tmux_binary_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "platform_root",
            "release_root",
            "repository_root",
            "remote_home",
            "python_executable",
            "node_executable",
            "java_executable",
            "platform_management_executable",
            "tmux_executable",
            "sha256sum_executable",
        ):
            _absolute(getattr(self, name), name)
        for name in (
            "tmux_binary_sha256",
            "python_binary_sha256",
            "python_packages_sha256",
            "node_binary_sha256",
            "java_binary_sha256",
            "platform_management_binary_sha256",
        ):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
                raise ValueError(f"{name} must be a SHA-256 hex digest")

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult


@dataclass(frozen=True, slots=True)
class ServerHealthReport:
    """A read-only health projection derived from one server command result."""

    server_id: str
    reachable: bool
    host_name: str | None
    python_version: str | None
    git_version: str | None
    tmux_version: str | None
    raw: ServerCommandResult
    platform_ready: bool = False
    checks: tuple[tuple[str, str], ...] = ()
    issues: tuple[str, ...] = ()


class ServerDiagnosticStatus(StrEnum):
    READY = "ready"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    REMOTE_NOT_READY = "remote_not_ready"


class ServerDiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ServerDiagnosticIssue:
    """One actionable fact in the read-only server diagnostic projection."""

    code: str
    severity: ServerDiagnosticSeverity
    summary: str
    evidence_refs: tuple[str, ...] = ()
    recommended_action: str | None = None


@dataclass(frozen=True, slots=True)
class ServerSessionDiagnostic:
    """Session observation copied into the server diagnostic projection."""

    session_name: str
    state: str
    summary: str
    controller_pid: int | None = None
    reason_code: str | None = None
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ServerDiagnosticReport:
    """Joined read-only view of remote health, operations and session state.

    The report owns no server state and performs no command.  It is a
    projection over already-observed facts whose profile digest is required
    to match the composition that produced the report.
    """

    server_id: str
    profile_digest: str
    operation_log: str
    health: ServerHealthReport
    pending_operations: tuple[ServerOperationRecord, ...]
    recent_operations: tuple[ServerOperationRecord, ...]
    session: ServerSessionDiagnostic | None
    issues: tuple[ServerDiagnosticIssue, ...]
    status: ServerDiagnosticStatus

    @property
    def ready_for_mutation(self) -> bool:
        return self.status == ServerDiagnosticStatus.READY


__all__ = [
    "ServerDiagnosticIssue",
    "ServerDiagnosticReport",
    "ServerDiagnosticSeverity",
    "ServerDiagnosticStatus",
    "ServerHealthReport",
    "ServerRuntimeHealthSpec",
    "ServerSessionDiagnostic",
]
