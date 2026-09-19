from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from typing import Iterable

from noetrium_platform.foundation.governance.api import (
    RepositorySourceBlob,
    RepositorySourceFailure,
    RepositorySourceFailureKind,
    RepositorySourceIncompleteError,
    RepositorySourceSnapshot,
)


DEFAULT_EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".local", ".server-state", "dist", "build",
})
DEFAULT_EXCLUDED_ROOT_FILES = frozenset({
    "RELEASE_MANIFEST.json",
    "RELEASE_EVIDENCE.json",
    "RELEASE_AUTHORITY.json",
    "DEVELOPMENT_SNAPSHOT_MANIFEST.sha256",
    "DEVELOPMENT_SNAPSHOT_METADATA.json",
    "DEVELOPMENT_ARCHITECTURE_REPORT.json",
})
DEFAULT_GOVERNANCE_SOURCE_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".sh", ".bash",
    ".json", ".yaml", ".yml", ".toml",
})


def _failure_path(root: Path, value: object | None) -> str:
    if value in {None, ""}:
        return "."
    candidate = Path(str(value))
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return candidate.as_posix()


class RepositorySourceTree:
    """Deterministic filesystem provider that either yields a complete cut or fails."""

    def __init__(
        self,
        root: Path,
        *,
        include_tests: bool = False,
        excluded_directories: frozenset[str] = DEFAULT_EXCLUDED_DIRECTORIES,
        excluded_root_files: frozenset[str] = DEFAULT_EXCLUDED_ROOT_FILES,
    ) -> None:
        self._root = Path(root).resolve()
        self._include_tests = include_tests
        self._excluded_directories = frozenset(excluded_directories)
        self._excluded_root_files = frozenset(excluded_root_files)
        if any(not name or "/" in name or "\\" in name for name in self._excluded_directories):
            raise ValueError("excluded directory entries must be single non-empty names")
        if any(not name or "/" in name or "\\" in name for name in self._excluded_root_files):
            raise ValueError("excluded root file entries must be single non-empty names")

    @property
    def root(self) -> Path:
        return self._root

    @property
    def include_tests(self) -> bool:
        return self._include_tests

    def _candidate_paths(self, supported: frozenset[str]) -> tuple[Path, ...]:
        candidates: list[Path] = []

        def onerror(exc: OSError) -> None:
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                RepositorySourceFailureKind.DIRECTORY_WALK,
                _failure_path(self._root, exc.filename),
                type(exc).__name__,
            ),)) from exc

        for directory, dirnames, filenames in os.walk(
            self._root,
            topdown=True,
            onerror=onerror,
        ):
            current = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in self._excluded_directories
                and not (not self._include_tests and current == self._root and name == "tests")
            )
            candidates.extend(
                current / filename
                for filename in filenames
                if (current / filename).suffix.lower() in supported
                and not (current == self._root and filename in self._excluded_root_files)
            )
        return tuple(sorted(
            candidates,
            key=lambda path: path.relative_to(self._root).as_posix(),
        ))

    def documents(self, *, suffixes: Iterable[str]) -> tuple[RepositorySourceBlob, ...]:
        """Materialize one complete deterministic source cut before exposing any blob.

        Algorithm-Complexity: O(N log N)
        Algorithm-Rationale: Directory discovery is linear in visited entries and the final stable path sort dominates at O(N log N); every selected file is read and decoded exactly once.
        """
        supported = frozenset(str(suffix).lower() for suffix in suffixes)
        if not supported:
            return ()
        blobs: list[RepositorySourceBlob] = []
        for path in self._candidate_paths(supported):
            relative = path.relative_to(self._root).as_posix()
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise RepositorySourceIncompleteError((RepositorySourceFailure(
                    RepositorySourceFailureKind.FILE_READ,
                    relative,
                    type(exc).__name__,
                ),)) from exc
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RepositorySourceIncompleteError((RepositorySourceFailure(
                    RepositorySourceFailureKind.UTF8_DECODE,
                    relative,
                    "invalid utf-8",
                ),)) from exc
            blobs.append(RepositorySourceBlob(
                relative_path=relative,
                suffix=path.suffix.lower(),
                sha256=hashlib.sha256(raw).hexdigest(),
                text=text,
            ))
        return tuple(blobs)

    def snapshot(
        self,
        *,
        suffixes: Iterable[str] = DEFAULT_GOVERNANCE_SOURCE_SUFFIXES,
    ) -> RepositorySourceSnapshot:
        return RepositorySourceSnapshot(self.documents(suffixes=suffixes))

    def index(
        self,
        *,
        suffixes: Iterable[str] = DEFAULT_GOVERNANCE_SOURCE_SUFFIXES,
    ) -> "RepositorySourceIndex":
        return RepositorySourceIndex(
            self.snapshot(suffixes=suffixes),
            source_authority="filesystem",
            source_revision=None,
        )


class RepositorySourceIndex:
    """Read-only IR over one source cut; Python syntax is parsed once at construction."""

    def __init__(
        self,
        snapshot: RepositorySourceSnapshot,
        *,
        source_authority: str,
        source_revision: str | None,
    ) -> None:
        authority = str(source_authority).strip()
        if not authority:
            raise ValueError("source_authority must be non-empty")
        self._snapshot = snapshot
        self._source_authority = authority
        self._source_revision = source_revision
        self._by_path = {blob.relative_path: blob for blob in snapshot.blobs}
        trees: dict[str, ast.Module] = {}
        for blob in snapshot.documents(suffixes={".py"}):
            try:
                trees[blob.relative_path] = _parse_python_source(
                    blob.text,
                    filename=blob.relative_path,
                )
            except SyntaxError as exc:
                raise RepositorySourceIncompleteError((RepositorySourceFailure(
                    RepositorySourceFailureKind.PYTHON_PARSE,
                    blob.relative_path,
                    f"line {exc.lineno or 0}",
                ),)) from exc
        self._python_trees = trees

    @property
    def snapshot(self) -> RepositorySourceSnapshot:
        return self._snapshot

    @property
    def source_digest(self) -> str:
        return self._snapshot.source_digest

    @property
    def source_authority(self) -> str:
        return self._source_authority

    @property
    def source_revision(self) -> str | None:
        return self._source_revision

    def documents(self, *, suffixes: Iterable[str]) -> tuple[RepositorySourceBlob, ...]:
        return self._snapshot.documents(suffixes=suffixes)

    def _blob(self, relative_path: str, sha256: str | None) -> RepositorySourceBlob:
        try:
            blob = self._by_path[relative_path]
        except KeyError as exc:
            raise KeyError(f"source path is not present in frozen index: {relative_path}") from exc
        if sha256 is not None and blob.sha256 != sha256:
            raise ValueError(f"source identity mismatch for {relative_path}")
        return blob

    def text(self, relative_path: str, *, sha256: str | None = None) -> str:
        return self._blob(relative_path, sha256).text

    def python_tree(self, relative_path: str, *, sha256: str | None = None) -> ast.Module:
        self._blob(relative_path, sha256)
        try:
            return self._python_trees[relative_path]
        except KeyError as exc:
            raise ValueError(f"source is not a Python document: {relative_path}") from exc


__all__ = [
    "DEFAULT_EXCLUDED_DIRECTORIES",
    "DEFAULT_EXCLUDED_ROOT_FILES",
    "DEFAULT_GOVERNANCE_SOURCE_SUFFIXES",
    "GitRepositorySourceTree",
    "RepositorySourceIndex",
    "RepositorySourceTree",
]

_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _git_executable(value: str | Path | None) -> str:
    configured = str(value or os.environ.get("NOETRIUM_GIT_EXECUTABLE", "")).strip()
    if configured:
        return configured
    discovered = shutil.which("git")
    if discovered:
        return discovered
    raise RepositorySourceIncompleteError((RepositorySourceFailure(
        RepositorySourceFailureKind.GIT_RESOLUTION,
        ".",
        "git executable unavailable",
    ),))


def _git_object_failure(detail: str) -> RepositorySourceIncompleteError:
    return RepositorySourceIncompleteError((RepositorySourceFailure(
        RepositorySourceFailureKind.GIT_OBJECT,
        ".",
        detail,
    ),))


_PEP695_TYPE_ALIAS_RE = re.compile(
    r"^(?P<indent>[ \t]*)type[ \t]+(?P<name>[A-Za-z_]\w*)"
    r"(?:\[[^\r\n]*\])?(?P<spacing>[ \t]*=)",
    re.MULTILINE,
)


def _parse_python_source(text: str, *, filename: str) -> ast.Module:
    """Parse source while allowing 3.11 to inspect older PEP 695 snapshots.

    Git-bound governance must preserve the original bytes, but a Python 3.11
    runner cannot parse the ``type Alias = ...`` statement introduced in 3.12.
    The compatibility projection only rewrites that declaration to an ordinary
    assignment for AST consumers; source identity and all non-compatibility
    syntax remain fail-closed.
    """

    try:
        return ast.parse(text, filename=filename)
    except SyntaxError as original:
        if sys.version_info >= (3, 12):
            raise
        projected = _PEP695_TYPE_ALIAS_RE.sub(
            lambda match: (
                f"{match.group('indent')}{match.group('name')}"
                f"{match.group('spacing')}"
            ),
            text,
        )
        if projected == text:
            raise
        try:
            return ast.parse(projected, filename=filename)
        except SyntaxError:
            raise original


class GitRepositorySourceTree:
    """Immutable repository provider backed by one exact Git commit archive."""

    def __init__(
        self,
        root: Path,
        *,
        revision: str = "HEAD",
        include_tests: bool = False,
        git_executable: str | Path | None = None,
        excluded_directories: frozenset[str] = DEFAULT_EXCLUDED_DIRECTORIES,
        excluded_root_files: frozenset[str] = DEFAULT_EXCLUDED_ROOT_FILES,
    ) -> None:
        self._root = Path(root).resolve()
        self._include_tests = bool(include_tests)
        self._git = _git_executable(git_executable)
        self._excluded_directories = frozenset(excluded_directories)
        self._excluded_root_files = frozenset(excluded_root_files)
        if any(not name or "/" in name or "\\" in name for name in self._excluded_directories):
            raise ValueError("excluded directory entries must be single non-empty names")
        requested = str(revision).strip()
        if not requested:
            raise ValueError("revision must be non-empty")
        self._revision = self._resolve_revision(requested)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def revision(self) -> str:
        return self._revision

    def _run_git(
        self, *arguments: str, failure_kind: RepositorySourceFailureKind = RepositorySourceFailureKind.GIT_RESOLUTION
    ) -> bytes:
        try:
            completed = subprocess.run(
                [self._git, "-C", str(self._root), *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                RepositorySourceFailureKind.GIT_RESOLUTION,
                ".",
                type(exc).__name__,
            ),)) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                failure_kind,
                ".",
                detail or f"git exit {completed.returncode}",
            ),))
        return completed.stdout

    def _resolve_revision(self, revision: str) -> str:
        raw = self._run_git("rev-parse", "--verify", f"{revision}^{{commit}}")
        resolved = raw.decode("ascii", errors="strict").strip()
        if _GIT_SHA_RE.fullmatch(resolved) is None:
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                RepositorySourceFailureKind.GIT_RESOLUTION,
                ".",
                "rev-parse did not return a canonical commit SHA",
            ),))
        return resolved

    def _selected(self, relative: str, supported: frozenset[str]) -> bool:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise _git_object_failure(f"non-canonical Git path: {relative}")
        if any(part in self._excluded_directories for part in path.parts[:-1]):
            return False
        if not self._include_tests and path.parts and path.parts[0] == "tests":
            return False
        if len(path.parts) == 1 and path.name in self._excluded_root_files:
            return False
        return path.suffix.lower() in supported

    def _tree_entries(
        self, supported: frozenset[str]
    ) -> tuple[tuple[str, str], ...]:
        raw = self._run_git(
            "ls-tree", "-r", "-z", "--full-tree", self._revision,
            failure_kind=RepositorySourceFailureKind.GIT_OBJECT,
        )
        entries: list[tuple[str, str]] = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, object_type, object_id = metadata.split(b" ", 2)
                relative = raw_path.decode("utf-8", errors="strict")
                oid = object_id.decode("ascii", errors="strict")
            except (ValueError, UnicodeDecodeError) as exc:
                raise _git_object_failure("invalid ls-tree record") from exc
            if not self._selected(relative, supported):
                continue
            if object_type != b"blob" or mode not in {b"100644", b"100755"}:
                raise _git_object_failure(
                    f"selected source is not a regular Git blob: {relative}"
                )
            if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid) is None:
                raise _git_object_failure(f"invalid Git object id for {relative}")
            entries.append((relative, oid))
        return tuple(sorted(entries, key=lambda item: item[0]))

    def _blob_bytes(
        self, entries: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, bytes], ...]:
        if not entries:
            return ()
        request = b"".join(oid.encode("ascii") + b"\n" for _relative, oid in entries)
        try:
            completed = subprocess.run(
                [self._git, "-C", str(self._root), "cat-file", "--batch"],
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise _git_object_failure(type(exc).__name__) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise _git_object_failure(detail or f"git cat-file exit {completed.returncode}")
        output = completed.stdout
        cursor = 0
        rows: list[tuple[str, bytes]] = []
        for relative, expected_oid in entries:
            newline = output.find(b"\n", cursor)
            if newline < 0:
                raise _git_object_failure(f"missing cat-file header for {relative}")
            header = output[cursor:newline]
            cursor = newline + 1
            fields = header.split(b" ")
            if len(fields) != 3 or fields[1] != b"blob":
                raise _git_object_failure(f"invalid cat-file header for {relative}")
            try:
                observed_oid = fields[0].decode("ascii", errors="strict")
                size = int(fields[2])
            except (UnicodeDecodeError, ValueError) as exc:
                raise _git_object_failure(f"invalid cat-file metadata for {relative}") from exc
            if observed_oid != expected_oid:
                raise _git_object_failure(f"cat-file identity mismatch for {relative}")
            payload_end = cursor + size
            raw = output[cursor:payload_end]
            if len(raw) != size or output[payload_end:payload_end + 1] != b"\n":
                raise _git_object_failure(f"truncated cat-file payload for {relative}")
            rows.append((relative, raw))
            cursor = payload_end + 1
        if cursor != len(output):
            raise _git_object_failure("unexpected trailing cat-file output")
        return tuple(rows)

    def documents(self, *, suffixes: Iterable[str]) -> tuple[RepositorySourceBlob, ...]:
        supported = frozenset(str(suffix).lower() for suffix in suffixes)
        if not supported:
            return ()
        entries = self._tree_entries(supported)
        blobs: list[RepositorySourceBlob] = []
        for relative, raw in self._blob_bytes(entries):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RepositorySourceIncompleteError((RepositorySourceFailure(
                    RepositorySourceFailureKind.UTF8_DECODE,
                    relative,
                    "invalid utf-8",
                ),)) from exc
            blobs.append(RepositorySourceBlob(
                relative_path=relative,
                suffix=PurePosixPath(relative).suffix.lower(),
                sha256=hashlib.sha256(raw).hexdigest(),
                text=text,
            ))
        return tuple(blobs)

    def snapshot(
        self,
        *,
        suffixes: Iterable[str] = DEFAULT_GOVERNANCE_SOURCE_SUFFIXES,
    ) -> RepositorySourceSnapshot:
        return RepositorySourceSnapshot(self.documents(suffixes=suffixes))

    def index(
        self,
        *,
        suffixes: Iterable[str] = DEFAULT_GOVERNANCE_SOURCE_SUFFIXES,
    ) -> RepositorySourceIndex:
        return RepositorySourceIndex(
            self.snapshot(suffixes=suffixes),
            source_authority="git",
            source_revision=self._revision,
        )
