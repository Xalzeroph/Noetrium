from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol


class RepositorySourceFailureKind(str, Enum):
    DIRECTORY_WALK = "directory_walk"
    FILE_READ = "file_read"
    UTF8_DECODE = "utf8_decode"
    PYTHON_PARSE = "python_parse"
    CONFIG_PARSE = "config_parse"
    GIT_RESOLUTION = "git_resolution"
    GIT_OBJECT = "git_object"


@dataclass(frozen=True, slots=True)
class RepositorySourceFailure:
    kind: RepositorySourceFailureKind
    relative_path: str
    detail: str


class RepositorySourceIncompleteError(RuntimeError):
    """Raised when a complete, internally consistent repository source cut cannot be built."""

    def __init__(self, failures: Iterable[RepositorySourceFailure]) -> None:
        self.failures = tuple(failures)
        if not self.failures:
            raise ValueError("repository source failure must contain at least one diagnostic")
        joined = "; ".join(
            f"{item.kind.value}:{item.relative_path}:{item.detail}" for item in self.failures
        )
        super().__init__(f"governance source snapshot incomplete: {joined}")


@dataclass(frozen=True, slots=True)
class RepositorySourceBlob:
    """Decoded repository source with identity bound to exact filesystem bytes."""

    relative_path: str
    suffix: str
    sha256: str
    text: str


class RepositorySourcePort(Protocol):
    """Read-only source discovery contract; scoring semantics stay with consumers."""

    def documents(self, *, suffixes: Iterable[str]) -> Iterable[RepositorySourceBlob]: ...


class RepositorySourceIndexPort(RepositorySourcePort, Protocol):
    """One immutable source cut plus the canonical parsed Python IR for that cut."""

    @property
    def source_digest(self) -> str: ...

    @property
    def source_authority(self) -> str: ...

    @property
    def source_revision(self) -> str | None: ...

    def text(self, relative_path: str, *, sha256: str | None = None) -> str: ...

    def python_tree(self, relative_path: str, *, sha256: str | None = None) -> ast.Module: ...


@dataclass(frozen=True, slots=True)
class RepositorySourceSnapshot:
    """Immutable source cut for multiple governance analyses over identical bytes."""

    blobs: tuple[RepositorySourceBlob, ...]

    def __post_init__(self) -> None:
        paths = tuple(blob.relative_path for blob in self.blobs)
        if paths != tuple(sorted(paths)):
            raise ValueError("repository source snapshot must be path-sorted")
        if len(paths) != len(set(paths)):
            raise ValueError("repository source snapshot contains duplicate paths")

    @property
    def source_digest(self) -> str:
        digest = hashlib.sha256()
        for blob in self.blobs:
            digest.update(blob.relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(blob.suffix.encode("ascii"))
            digest.update(b"\0")
            digest.update(blob.sha256.encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    def documents(self, *, suffixes: Iterable[str]) -> tuple[RepositorySourceBlob, ...]:
        supported = frozenset(str(suffix).lower() for suffix in suffixes)
        if not supported:
            return ()
        return tuple(blob for blob in self.blobs if blob.suffix in supported)


def repository_source_scope_digest(
    source_index: RepositorySourceIndexPort,
    *,
    path_prefixes: Iterable[str],
    suffixes: Iterable[str] = (".py",),
) -> str:
    """Digest selected immutable source blobs by canonical repository path.

    The digest is independent of filesystem timestamps and iteration order. Prefixes
    are repository-relative POSIX paths; unknown/empty scopes fail closed.
    """

    prefixes = tuple(str(value).strip().strip("/") for value in path_prefixes)
    if not prefixes or any(
        not value or "\\" in value or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        for value in prefixes
    ):
        raise ValueError("path_prefixes must be canonical non-empty repository-relative POSIX paths")
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("path_prefixes must be unique")
    supported = tuple(str(value).strip().lower() for value in suffixes)
    if not supported or any(not value.startswith(".") or len(value) < 2 for value in supported):
        raise ValueError("suffixes must contain canonical file suffixes")
    rows = tuple(sorted(
        (blob.relative_path, blob.sha256)
        for blob in source_index.documents(suffixes=supported)
        if any(
            blob.relative_path == prefix
            or blob.relative_path.startswith(prefix + "/")
            for prefix in prefixes
        )
    ))
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def repository_source_scope_text_digest(
    source_index: RepositorySourceIndexPort,
    *,
    path_prefixes: Iterable[str],
    suffixes: Iterable[str] = (".py",),
) -> str:
    """Digest canonical UTF-8 source text while ignoring checkout line-ending policy.

    This identity is for executable/analyzer implementation semantics: CRLF and LF
    checkouts of the same Git source are equivalent, while every other text change
    remains identity-changing. Raw repository byte identity stays available through
    ``repository_source_scope_digest`` and the source index itself.
    """

    prefixes = tuple(str(value).strip().strip("/") for value in path_prefixes)
    if not prefixes or any(
        not value or "\\" in value or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        for value in prefixes
    ):
        raise ValueError("path_prefixes must be canonical non-empty repository-relative POSIX paths")
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("path_prefixes must be unique")
    supported = tuple(str(value).strip().lower() for value in suffixes)
    if not supported or any(not value.startswith(".") or len(value) < 2 for value in supported):
        raise ValueError("suffixes must contain canonical file suffixes")
    rows = []
    for blob in source_index.documents(suffixes=supported):
        if not any(
            blob.relative_path == prefix
            or blob.relative_path.startswith(prefix + "/")
            for prefix in prefixes
        ):
            continue
        canonical_text = blob.text.replace("\r\n", "\n").replace("\r", "\n")
        rows.append((
            blob.relative_path,
            hashlib.sha256(canonical_text.encode("utf-8")).hexdigest(),
        ))
    payload = json.dumps(tuple(sorted(rows)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "RepositorySourceBlob",
    "RepositorySourceFailure",
    "RepositorySourceFailureKind",
    "RepositorySourceIncompleteError",
    "RepositorySourceIndexPort",
    "RepositorySourcePort",
    "RepositorySourceSnapshot",
    "repository_source_scope_digest",
    "repository_source_scope_text_digest",
]
