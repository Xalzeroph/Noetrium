from __future__ import annotations

from dataclasses import dataclass
import re


_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_GITHUB_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$")


class ServerRepositorySyncError(RuntimeError):
    """A server-side repository synchronization failed at a named phase."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(f"server repository synchronization failed at {phase}: {message}")
        self.phase = phase


@dataclass(frozen=True, slots=True)
class ServerRepositorySyncRequest:
    """One exact GitHub source and revision to materialize on a managed server."""

    repository_url: str
    repository_name: str
    revision: str

    def __post_init__(self) -> None:
        if _GITHUB_RE.fullmatch(self.repository_url) is None:
            raise ValueError("repository_url must be an HTTPS GitHub .git URL")
        if _REPOSITORY_NAME_RE.fullmatch(self.repository_name) is None:
            raise ValueError("repository_name contains unsafe or unsupported characters")
        if _COMMIT_RE.fullmatch(self.revision) is None:
            raise ValueError("revision must be a 40-character commit SHA")
        object.__setattr__(self, "revision", self.revision.lower())


@dataclass(frozen=True, slots=True)
class ServerRepositorySyncReceipt:
    server_id: str
    repository_url: str
    repository_name: str
    revision: str
    target_path: str
    command_return_code: int
    profile_digest: str


@dataclass(frozen=True, slots=True)
class ServerRepositoryStatus:
    server_id: str
    repository_name: str
    target_path: str
    exists: bool
    head: str | None
    origin: str | None
    dirty: bool | None
    staging_exists: bool
    target_kind: str
    staging_kind: str
    target_children: tuple[str, ...]


__all__ = [
    "ServerRepositorySyncError",
    "ServerRepositorySyncReceipt",
    "ServerRepositorySyncRequest",
    "ServerRepositoryStatus",
]
