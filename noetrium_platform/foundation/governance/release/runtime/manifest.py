from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

from noetrium_platform.foundation.governance.release.api import FileDigest, ReleaseManifest
from .project_metadata import load_project_metadata


EXCLUDED_DIRS = {"__pycache__", ".git", ".local", ".pytest_cache", ".server-state", "build", "dist", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAME_MARKERS = (".local.",)
DERIVED_RELEASE_FILES = {
    "RELEASE_MANIFEST.json",
    "RELEASE_EVIDENCE.json",
    "RELEASE_AUTHORITY.json",
    "DEVELOPMENT_SNAPSHOT_MANIFEST.sha256",
    "DEVELOPMENT_SNAPSHOT_METADATA.json",
    "DEVELOPMENT_ARCHITECTURE_REPORT.json",
}
_HASH_CHUNK_BYTES = 1024 * 1024


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def _excluded_dir_name(name: str) -> bool:
    return name in EXCLUDED_DIRS or name.endswith(".egg-info")


def _iter_release_files(root: Path) -> Iterator[tuple[Path, Path]]:
    """Yield release files in deterministic lexical order without materializing rglob().

    Algorithm-Complexity: O(N)
    Algorithm-Rationale: os.walk partitions each filesystem entry into exactly one directory listing, so nested syntax is a sum over entries rather than a Cartesian product.

    ``os.walk`` lets us prune excluded subtrees before descending into them.  On
    large worktrees this avoids stat'ing cache/build trees that can never enter a
    release manifest while preserving byte-for-byte deterministic ordering.
    """

    root = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not _excluded_dir_name(name))
        base = Path(dirpath)
        for name in sorted(filenames):
            path = base / name
            rel = path.relative_to(root)
            if path.suffix in EXCLUDED_SUFFIXES:
                continue
            if any(marker in name for marker in EXCLUDED_NAME_MARKERS):
                continue
            if rel.as_posix() in DERIVED_RELEASE_FILES:
                continue
            yield path, rel


def build_release_manifest(
    root: Path,
    *,
    platform_code_version: str | None = None,
    python_requires: str | None = None,
) -> ReleaseManifest:
    root = Path(root).resolve()
    metadata = load_project_metadata(root)
    resolved_version = metadata.version if platform_code_version is None else platform_code_version
    resolved_python = metadata.python_requires if python_requires is None else python_requires
    files: list[FileDigest] = []
    for path, rel in _iter_release_files(root):
        # stat once for size; the content digest itself is always exact and never
        # trusts mtime/size caches in the claim-grade release path.
        stat = path.stat()
        files.append(FileDigest(rel.as_posix(), hash_file(path), stat.st_size))
    tree_raw = "\n".join(f"{x.sha256}  {x.path}  {x.size}" for x in files).encode("utf-8")
    return ReleaseManifest(
        1,
        tuple(files),
        hashlib.sha256(tree_raw).hexdigest(),
        resolved_python,
        resolved_version,
    )


def verify_release_manifest(
    root: Path,
    manifest: ReleaseManifest,
    *,
    actual_manifest: ReleaseManifest | None = None,
) -> tuple[str, ...]:
    """Verify one frozen manifest with exactly one source-tree rebuild.

    Callers that already hold a freshly-built exact snapshot may pass it through,
    preventing the pipeline from re-hashing thousands of files at every layer.
    """

    actual = actual_manifest or build_release_manifest(
        root,
        platform_code_version=manifest.platform_code_version,
        python_requires=manifest.python_requires,
    )
    errors: list[str] = []
    actual_by_path = {x.path: x for x in actual.files}
    expected_by_path = {x.path: x for x in manifest.files}
    for path in sorted(expected_by_path.keys() - actual_by_path.keys()):
        errors.append(f"missing file: {path}")
    for path in sorted(actual_by_path.keys() - expected_by_path.keys()):
        errors.append(f"unexpected file: {path}")
    for path in sorted(expected_by_path.keys() & actual_by_path.keys()):
        expected = expected_by_path[path]
        observed = actual_by_path[path]
        if expected.sha256 != observed.sha256 or expected.size != observed.size:
            errors.append(f"file drift: {path}")
    if actual.source_tree_sha256 != manifest.source_tree_sha256:
        errors.append("source tree digest mismatch")
    return tuple(errors)


__all__ = [
    "DERIVED_RELEASE_FILES",
    "EXCLUDED_DIRS",
    "EXCLUDED_NAME_MARKERS",
    "EXCLUDED_SUFFIXES",
    "build_release_manifest",
    "hash_file",
    "verify_release_manifest",
]
