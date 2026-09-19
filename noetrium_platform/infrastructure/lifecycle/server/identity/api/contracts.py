from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from enum import StrEnum
import math
import re
from types import MappingProxyType
from collections.abc import Mapping


class ServerIdentityConfigurationError(ValueError):
    """A server profile is incomplete or contains an unsafe value."""


class ServerProfileCatalogError(ValueError):
    """A multi-server profile has ambiguous or incomplete membership."""


class ServerAuthenticationUnavailable(RuntimeError):
    """The requested non-interactive connection has no usable SSH identity."""


class ServerTransportFailureKind(StrEnum):
    """Stable classification of an SSH/SCP transport result."""

    NONE = "none"
    REMOTE_EXIT = "remote_exit"
    AUTHENTICATION = "authentication"
    NETWORK = "network"
    TIMEOUT = "timeout"
    SPAWN_ERROR = "spawn_error"


@dataclass(frozen=True, slots=True)
class ServerConnectionProfile:
    """Non-secret connection identity for one managed remote host.

    Values are materialized from the process environment at composition time.
    Passwords are deliberately not represented here: automated runs use an SSH
    key or agent, while an interactive run may let OpenSSH prompt on its TTY.
    """

    server_id: str
    host: str
    port: int
    username: str
    key_path: Path | None = None
    known_hosts_path: Path | None = None
    ssh_config_path: Path | None = None
    ssh_executable: str = "ssh"
    connect_timeout_seconds: int = 15
    control_path: Path | None = None
    control_persist_seconds: int = 600
    command_timeout_seconds: float = 120.0
    interactive_timeout_seconds: float = 8 * 60 * 60.0
    transfer_timeout_seconds: float = 1800.0
    repository_timeout_seconds: float = 1800.0
    git_transport_timeout_seconds: float = 120.0
    output_limit_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.server_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.server_id):
            raise ServerIdentityConfigurationError("server_id must be a safe non-empty identifier")
        if not self.host or any(char.isspace() for char in self.host):
            raise ServerIdentityConfigurationError("server host must be non-empty and contain no whitespace")
        if not 1 <= self.port <= 65535:
            raise ServerIdentityConfigurationError("server port must be in [1, 65535]")
        if not self.username or any(char.isspace() for char in self.username):
            raise ServerIdentityConfigurationError("server username must be non-empty and contain no whitespace")
        if not self.ssh_executable:
            raise ServerIdentityConfigurationError("ssh executable must be non-empty")
        if not math.isfinite(float(self.connect_timeout_seconds)) or self.connect_timeout_seconds <= 0:
            raise ServerIdentityConfigurationError("SSH connect timeout must be finite and positive")
        if self.control_path is not None:
            if not self.control_path.is_absolute():
                raise ServerIdentityConfigurationError("SSH control path must be absolute")
            control_text = str(self.control_path)
            if any(char in control_text for char in "\x00\r\n"):
                raise ServerIdentityConfigurationError("SSH control path contains unsafe characters")
            # OpenSSH Unix-domain control sockets are limited to 108 bytes.
            # Validate the worst-case supported template before any network
            # operation; otherwise a long path is misreported as a remote
            # connectivity failure. ``%C`` is the only dynamic token owned by
            # this platform and expands to a 40-character connection digest.
            dynamic_tokens = control_text.replace("%%", "").replace("%C", "")
            if "%" in dynamic_tokens:
                raise ServerIdentityConfigurationError(
                    "SSH control path may contain only the %C or %% OpenSSH token"
                )
            expanded_length = len(
                control_text.replace("%C", "0" * 40).replace("%%", "%").encode("utf-8")
            )
            if expanded_length >= 108:
                raise ServerIdentityConfigurationError(
                    "SSH control path template expands to 108 or more bytes; use a shorter local path"
                )
        if not math.isfinite(float(self.control_persist_seconds)) or self.control_persist_seconds <= 0:
            raise ServerIdentityConfigurationError("SSH control persist seconds must be finite and positive")
        if not math.isfinite(float(self.command_timeout_seconds)) or self.command_timeout_seconds <= 0:
            raise ServerIdentityConfigurationError("SSH command timeout must be finite and positive")
        if not math.isfinite(float(self.interactive_timeout_seconds)) or self.interactive_timeout_seconds <= 0:
            raise ServerIdentityConfigurationError("SSH interactive timeout must be finite and positive")
        if not math.isfinite(float(self.transfer_timeout_seconds)) or self.transfer_timeout_seconds <= 0:
            raise ServerIdentityConfigurationError("SCP transfer timeout must be finite and positive")
        if not math.isfinite(float(self.repository_timeout_seconds)) or self.repository_timeout_seconds <= 0:
            raise ServerIdentityConfigurationError("repository command timeout must be finite and positive")
        if not math.isfinite(float(self.git_transport_timeout_seconds)) or self.git_transport_timeout_seconds <= 0:
            raise ServerIdentityConfigurationError("Git transport timeout must be finite and positive")
        if self.git_transport_timeout_seconds > self.repository_timeout_seconds:
            raise ServerIdentityConfigurationError(
                "Git transport timeout must not exceed repository command timeout"
            )
        if self.output_limit_bytes <= 0:
            raise ServerIdentityConfigurationError("SSH output limit must be positive")

    @property
    def destination(self) -> str:
        return f"{self.username}@{self.host}"


@dataclass(frozen=True, slots=True)
class ServerCommandResult:
    server_id: str
    command: str
    return_code: int
    stdout: str
    stderr: str
    failure_kind: ServerTransportFailureKind = ServerTransportFailureKind.NONE
    duration_seconds: float = 0.0
    stdout_bytes: int = 0
    stderr_bytes: int = 0

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0 and self.failure_kind == ServerTransportFailureKind.NONE


@dataclass(frozen=True, slots=True)
class ServerFileTransferResult:
    server_id: str
    local_path: str
    remote_path: str
    return_code: int
    stdout: str
    stderr: str
    failure_kind: ServerTransportFailureKind = ServerTransportFailureKind.NONE
    duration_seconds: float = 0.0
    stdout_bytes: int = 0
    stderr_bytes: int = 0

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0 and self.failure_kind == ServerTransportFailureKind.NONE


def server_environment_prefix(server_id: str, *, root: str = "RP_SERVER") -> str:
    token = re.sub(r"[^A-Za-z0-9]", "_", server_id).upper()
    if not token or token[0].isdigit():
        token = "S_" + token
    return f"{root}_{token}"


@dataclass(frozen=True, slots=True)
class ServerProfileCatalogEntry:
    """A non-secret projection of one declared server profile.

    The catalog is intentionally a schema projection, not only a membership
    list. Missing connection fields are separated from missing runtime fields
    so an offline doctor can explain a local defect without attempting SSH.
    """

    server_id: str
    prefix: str
    configured_fields: tuple[str, ...]
    missing_identity_fields: tuple[str, ...] = ()
    missing_runtime_fields: tuple[str, ...] = ()

    @property
    def missing_profile_fields(self) -> tuple[str, ...]:
        return self.missing_identity_fields + self.missing_runtime_fields

    @property
    def composition_ready(self) -> bool:
        return not self.missing_profile_fields


@dataclass(frozen=True, slots=True)
class ServerProfileCatalog:
    """Immutable membership projection of one profile source.

    The catalog is deliberately not a provider locator.  It contains only
    declared server identities and can derive an environment narrowed to one
    identity; composition still materializes the actual server adapters.
    """

    source: str
    entries: tuple[ServerProfileCatalogEntry, ...]
    _environment: Mapping[str, str] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.source:
            raise ServerProfileCatalogError("server profile catalog source is required")
        if not self.entries:
            raise ServerProfileCatalogError("server profile catalog must declare at least one server")
        ids = tuple(entry.server_id for entry in self.entries)
        if len(ids) != len(set(ids)):
            raise ServerProfileCatalogError("server profile catalog contains duplicate server ids")
        object.__setattr__(self, "_environment", MappingProxyType(dict(self._environment)))

    @property
    def server_ids(self) -> tuple[str, ...]:
        return tuple(entry.server_id for entry in self.entries)

    def entry(self, server_id: str) -> ServerProfileCatalogEntry:
        for entry in self.entries:
            if entry.server_id == server_id:
                return entry
        raise ServerProfileCatalogError(f"server id is not declared in the profile catalog: {server_id}")

    def environment_for(self, server_id: str) -> Mapping[str, str]:
        """Return only non-server values and the selected server's namespace."""

        entry = self.entry(server_id)
        prefix = entry.prefix + "_"
        selected = {
            key: value
            for key, value in self._environment.items()
            if not key.startswith("RP_SERVER_") or key.startswith(prefix)
        }
        return MappingProxyType(selected)


__all__ = [
    "ServerAuthenticationUnavailable",
    "ServerCommandResult",
    "ServerConnectionProfile",
    "ServerFileTransferResult",
    "ServerIdentityConfigurationError",
    "ServerProfileCatalog",
    "ServerProfileCatalogEntry",
    "ServerProfileCatalogError",
    "ServerTransportFailureKind",
    "server_environment_prefix",
]
