from __future__ import annotations

from dataclasses import dataclass
import posixpath
import re

from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
)


_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")


def _normalize_relative_cwd(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("relative_cwd must be a relative POSIX path")
    if not value:
        return ""
    if "\x00" in value or value.startswith("/") or "\\" in value:
        raise ValueError("relative_cwd must be a relative POSIX path")
    normalized = posixpath.normpath(value)
    if normalized in {"", "."}:
        return ""
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("relative_cwd must remain inside the repository")
    return normalized


@dataclass(frozen=True, slots=True)
class ServerRepositoryCommandRequest:
    """One command pinned to a clean, exact repository checkout.

    The command is an argv vector rather than shell text.  The provider quotes
    each argument before composing the remote command, so a project can run a
    persistent test/experiment entrypoint without receiving a raw SSH seam.
    """

    repository_name: str
    revision: str
    command_argv: tuple[str, ...]
    relative_cwd: str = ""

    def __post_init__(self) -> None:
        if _REPOSITORY_NAME_RE.fullmatch(self.repository_name) is None:
            raise ValueError("repository_name contains unsafe or unsupported characters")
        if _COMMIT_RE.fullmatch(self.revision) is None:
            raise ValueError("revision must be a 40-character commit SHA")
        argv = tuple(self.command_argv)
        if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
            raise ValueError("command_argv must contain non-empty strings without NUL bytes")
        if len(argv) > 256:
            raise ValueError("command_argv is too large")
        object.__setattr__(self, "revision", self.revision.lower())
        object.__setattr__(self, "command_argv", argv)
        object.__setattr__(self, "relative_cwd", _normalize_relative_cwd(self.relative_cwd))


@dataclass(frozen=True, slots=True)
class ServerRepositoryCommandReceipt:
    server_id: str
    repository_name: str
    revision: str
    target_path: str
    working_directory: str
    command_argv: tuple[str, ...]
    command_result: ServerCommandResult
    profile_digest: str

    @property
    def succeeded(self) -> bool:
        return self.command_result.succeeded


__all__ = [
    "ServerRepositoryCommandReceipt",
    "ServerRepositoryCommandRequest",
]
