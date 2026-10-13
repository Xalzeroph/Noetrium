from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import posixpath
import re
import shlex

from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerFileTransferResult,
    server_environment_prefix,
)


class ServerReleaseDeploymentError(RuntimeError):
    """A content-addressed remote release could not be published exactly."""

    def __init__(self, phase: str, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(f"server release deployment failed at {phase}: {message}")
        self.phase = phase
        self.cause = cause


def _require_digest(value: str, *, field: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return value.lower()


def _required_profile_value(values: Mapping[str, str], prefix: str, name: str) -> str:
    value = values.get(f"{prefix}_{name}", "").strip()
    if not value:
        raise ValueError(f"missing environment variable {prefix}_{name}")
    return value


def _absolute_remote_path(value: str, *, field: str) -> str:
    if not posixpath.isabs(value):
        raise ValueError(f"{field} must be an absolute POSIX path")
    normalized = posixpath.normpath(value)
    if normalized == "/":
        raise ValueError(f"{field} must not be the POSIX filesystem root")
    return normalized


@dataclass(frozen=True, slots=True)
class ServerRemoteProfile:
    """Non-secret remote runtime profile shared by server operator tooling.

    SSH identity remains owned by ``runtime/server/identity``. This profile
    owns only remote lifecycle paths and the exact remote operator-session
    transport. It is materialized from environment, never guessed by a
    script, so connection, release and recovery commands share one profile.
    """

    server_id: str
    platform_root: str
    release_root: str
    operator_cwd: str
    repository_root: str
    operator_shell: str
    operator_shell_args: tuple[str, ...]
    remote_env_executable: str
    sha256sum_executable: str
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
    tmux_binary_sha256: str
    tmux_server_label: str
    tmux_config_file: str
    tmux_socket_directory: str
    session_name: str
    local_binding_root: Path
    remote_home: str
    remote_path: str
    remote_term: str

    @classmethod
    def from_environment(
        cls,
        server_id: str,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "ServerRemoteProfile":
        import os

        values = os.environ if environ is None else environ
        prefix = server_environment_prefix(server_id)
        platform_root = _absolute_remote_path(
            _required_profile_value(values, prefix, "PLATFORM_ROOT"),
            field=f"{prefix}_PLATFORM_ROOT",
        )
        release_root = _absolute_remote_path(
            values.get(f"{prefix}_RELEASE_ROOT", platform_root).strip() or platform_root,
            field=f"{prefix}_RELEASE_ROOT",
        )
        operator_cwd = _absolute_remote_path(
            _required_profile_value(values, prefix, "OPERATOR_CWD"),
            field=f"{prefix}_OPERATOR_CWD",
        )
        repository_root = _absolute_remote_path(
            _required_profile_value(values, prefix, "REPOSITORY_ROOT"),
            field=f"{prefix}_REPOSITORY_ROOT",
        )
        operator_shell = _required_profile_value(values, prefix, "OPERATOR_SHELL")
        operator_shell_args_text = _required_profile_value(values, prefix, "OPERATOR_SHELL_ARGS")
        try:
            operator_shell_args = tuple(shlex.split(operator_shell_args_text, posix=True))
        except ValueError as exc:
            raise ValueError(f"{prefix}_OPERATOR_SHELL_ARGS is not valid argv text") from exc
        if not operator_shell_args or any("\x00" in value for value in operator_shell_args):
            raise ValueError(f"{prefix}_OPERATOR_SHELL_ARGS must contain a non-empty safe argv")
        remote_env = _required_profile_value(values, prefix, "REMOTE_ENV")
        sha256sum = _required_profile_value(values, prefix, "SHA256SUM")
        python_executable = _required_profile_value(values, prefix, "PYTHON")
        python_binary_sha256 = _required_profile_value(values, prefix, "PYTHON_SHA256").lower()
        node_executable = _required_profile_value(values, prefix, "NODE")
        node_binary_sha256 = _required_profile_value(values, prefix, "NODE_SHA256").lower()
        java_executable = _required_profile_value(values, prefix, "JAVA")
        java_binary_sha256 = _required_profile_value(values, prefix, "JAVA_SHA256").lower()
        management_executable = _required_profile_value(values, prefix, "PLATFORM_MANAGE")
        management_binary_sha256 = _required_profile_value(values, prefix, "PLATFORM_MANAGE_SHA256").lower()
        for name, digest in (
            ("PYTHON_SHA256", python_binary_sha256),
            ("NODE_SHA256", node_binary_sha256),
            ("JAVA_SHA256", java_binary_sha256),
            ("PLATFORM_MANAGE_SHA256", management_binary_sha256),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"{prefix}_{name} must be a SHA-256 hex digest")
        python_packages_sha256 = _required_profile_value(values, prefix, "PYTHON_PACKAGES_SHA256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", python_packages_sha256):
            raise ValueError(f"{prefix}_PYTHON_PACKAGES_SHA256 must be a SHA-256 hex digest")
        tmux = _required_profile_value(values, prefix, "TMUX")
        tmux_digest = _required_profile_value(values, prefix, "TMUX_SHA256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", tmux_digest):
            raise ValueError(f"{prefix}_TMUX_SHA256 must be a SHA-256 hex digest")
        config_file = _required_profile_value(values, prefix, "TMUX_CONFIG")
        socket_directory = _absolute_remote_path(
            _required_profile_value(values, prefix, "TMUX_SOCKET_DIRECTORY"),
            field=f"{prefix}_TMUX_SOCKET_DIRECTORY",
        )
        local_binding_input = Path(_required_profile_value(values, prefix, "LOCAL_BINDING_ROOT")).expanduser()
        if not local_binding_input.is_absolute():
            raise ValueError(f"{prefix}_LOCAL_BINDING_ROOT must be an absolute local path")
        local_binding = local_binding_input.resolve()
        remote_home = _absolute_remote_path(
            _required_profile_value(values, prefix, "REMOTE_HOME"),
            field=f"{prefix}_REMOTE_HOME",
        )
        remote_path = _required_profile_value(values, prefix, "REMOTE_PATH")
        remote_term = _required_profile_value(values, prefix, "TERM")
        if any(char in remote_term for char in "\x00\r\n") or not remote_term.strip():
            raise ValueError(f"{prefix}_TERM contains unsafe characters")
        session_name = _required_profile_value(values, prefix, "SESSION_NAME")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", session_name) is None:
            raise ValueError(f"{prefix}_SESSION_NAME contains unsafe session characters")
        for value, field in (
            (operator_shell, "OPERATOR_SHELL"),
            (remote_env, "REMOTE_ENV"),
            (sha256sum, "SHA256SUM"),
            (python_executable, "PYTHON"),
            (node_executable, "NODE"),
            (java_executable, "JAVA"),
            (management_executable, "PLATFORM_MANAGE"),
            (tmux, "TMUX"),
        ):
            if not posixpath.isabs(value):
                raise ValueError(f"{prefix}_{field} must be an absolute remote path")
        if not config_file.startswith("/"):
            raise ValueError(f"{prefix}_TMUX_CONFIG must be an absolute remote path")
        server_label = _required_profile_value(values, prefix, "TMUX_SERVER_LABEL")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", server_label) is None:
            raise ValueError(f"{prefix}_TMUX_SERVER_LABEL contains unsafe characters")
        return cls(
            server_id,
            platform_root,
            release_root,
            operator_cwd,
            repository_root,
            operator_shell,
            operator_shell_args,
            remote_env,
            sha256sum,
            python_executable,
            python_binary_sha256,
            python_packages_sha256,
            node_executable,
            node_binary_sha256,
            java_executable,
            java_binary_sha256,
            management_executable,
            management_binary_sha256,
            tmux,
            tmux_digest,
            server_label,
            config_file,
            socket_directory,
            session_name,
            local_binding,
            remote_home,
            remote_path,
            remote_term,
        )

    @property
    def session_environment(self) -> tuple[tuple[str, str], ...]:
        return (
            ("HOME", self.remote_home),
            ("LANG", "C.UTF-8"),
            ("LC_ALL", "C"),
            ("PATH", self.remote_path),
            ("TERM", self.remote_term),
        )


@dataclass(frozen=True, slots=True)
class ServerReleaseLayout:
    """Explicit POSIX target layout for immutable server releases."""

    root: str

    def __post_init__(self) -> None:
        if not posixpath.isabs(self.root):
            raise ValueError("server release root must be an absolute POSIX target path")
        normalized = posixpath.normpath(self.root)
        if normalized == "/":
            raise ValueError("server release root must not be the POSIX filesystem root")
        object.__setattr__(self, "root", normalized)

    @property
    def incoming_root(self) -> str:
        return posixpath.join(self.root, "incoming")

    @property
    def releases_root(self) -> str:
        return posixpath.join(self.root, "releases")

    def archive_path(self, release_digest: str) -> str:
        digest = _require_digest(release_digest, field="release_digest")
        return posixpath.join(self.incoming_root, f"{digest}.zip")

    def upload_path(self, release_digest: str) -> str:
        digest = _require_digest(release_digest, field="release_digest")
        return posixpath.join(self.incoming_root, f"{digest}.zip.part")

    def release_path(self, release_digest: str) -> str:
        digest = _require_digest(release_digest, field="release_digest")
        return posixpath.join(self.releases_root, digest)


@dataclass(frozen=True, slots=True)
class ServerReleaseDeploymentRequest:
    release_digest: str
    local_package: Path
    layout: ServerReleaseLayout

    def __post_init__(self) -> None:
        object.__setattr__(self, "release_digest", _require_digest(self.release_digest, field="release_digest"))
        if not self.local_package.is_absolute():
            raise ValueError("local release package must be an absolute path")


@dataclass(frozen=True, slots=True)
class ServerReleaseDeploymentReceipt:
    server_id: str
    release_digest: str
    remote_archive: str
    remote_release_dir: str
    uploaded: bool
    preparation: ServerCommandResult
    transfer: ServerFileTransferResult | None
    finalization: ServerCommandResult | None


__all__ = [
    "ServerReleaseDeploymentError",
    "ServerReleaseDeploymentReceipt",
    "ServerReleaseDeploymentRequest",
    "ServerReleaseLayout",
]
