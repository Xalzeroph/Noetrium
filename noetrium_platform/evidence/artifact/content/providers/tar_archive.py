from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from ._publication import (
    PublicationLock,
    PublicationLockBusy,
    PublicationLockUnavailable,
    fsync_directory,
)
from ._tar_extract import extract_tar_plan
from ._tar_plan import plan_tar_archive

from ..api.materialization import (
    ArchiveMaterializationError,
    ArchiveMaterializationPort,
    ArchiveMaterializationRequest,
    ArchiveMaterializationResult,
    MaterializedTreeInspection,
    MaterializedTreeInspectionPort,
)


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _iter_tree_entries(base: Path):
    def walk(directory: Path, prefix: PurePosixPath):
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        for entry in entries:
            path = Path(entry.path)
            relative = prefix / entry.name
            yield relative.as_posix(), path
            if entry.is_dir(follow_symlinks=False):
                yield from walk(path, relative)

    yield from walk(base, PurePosixPath())


def digest_materialized_tree(root: str | Path) -> tuple[str, int, int]:
    """Return a stable streaming digest over paths, modes, links and file bytes."""

    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise ArchiveMaterializationError(
            "TREE_MISSING", f"materialized tree is missing: {base}"
        )
    digest = hashlib.sha256()
    file_count = 0
    expanded_size = 0
    for relative, path in _iter_tree_entries(base):
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode) & 0o777
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{mode:o}".encode("ascii"))
        digest.update(b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(b"link\0")
            digest.update(os.readlink(path).encode("utf-8"))
        elif stat.S_ISDIR(metadata.st_mode):
            digest.update(b"dir")
        elif stat.S_ISREG(metadata.st_mode):
            digest.update(b"file\0")
            file_digest, size = _sha256_file(path)
            digest.update(file_digest.encode("ascii"))
            file_count += 1
            expanded_size += size
        else:
            raise ArchiveMaterializationError(
                "TREE_ENTRY_UNSUPPORTED",
                f"unsupported materialized tree entry: {relative}",
            )
        digest.update(b"\0")
    return digest.hexdigest(), file_count, expanded_size


def _fsync_tree_directories(root: Path) -> None:
    directories: list[Path] = []
    for directory, names, _ in os.walk(root, followlinks=False):
        current = Path(directory)
        directories.append(current)
        for name in names:
            child = current / name
            if child.is_dir() and not child.is_symlink():
                directories.append(child)
    seen: set[Path] = set()
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        if directory in seen:
            continue
        seen.add(directory)
        fsync_directory(directory)


def _publish_tree(candidate: Path, destination: Path, expected_digest: str) -> tuple[str, int, int]:
    guard = destination.with_name(f".{destination.name}.materialize.lock")
    try:
        with PublicationLock(guard):
            if destination.exists() or destination.is_symlink():
                raise ArchiveMaterializationError(
                    "DESTINATION_EXISTS",
                    f"materialization destination already exists: {destination}",
                )
            _fsync_tree_directories(candidate)
            candidate.replace(destination)
            fsync_directory(destination.parent)
            inspection = digest_materialized_tree(destination)
            if inspection[0] != expected_digest:
                raise ArchiveMaterializationError(
                    "POST_PUBLICATION_DIGEST_MISMATCH",
                    "materialized tree changed during atomic publication",
                )
            return inspection
    except PublicationLockBusy as exc:
        raise ArchiveMaterializationError(
            "PUBLICATION_BUSY",
            f"another publisher owns the destination transaction: {destination}",
        ) from exc
    except PublicationLockUnavailable as exc:
        raise ArchiveMaterializationError(
            "PUBLICATION_LOCK_UNAVAILABLE",
            "artifact publication lock could not be acquired safely",
        ) from exc


def _validated_candidate(
    staging: Path,
    top_level: str,
    required_relative_paths: tuple[str, ...],
) -> Path:
    candidate = staging / top_level
    if not candidate.is_dir() or candidate.is_symlink():
        raise ArchiveMaterializationError(
            "TOP_LEVEL_LAYOUT", "archive root was not materialized"
        )
    for relative in required_relative_paths:
        required = candidate.joinpath(
            *PurePosixPath(relative.replace("\\", "/")).parts
        )
        if not required.is_file():
            raise ArchiveMaterializationError(
                "REQUIRED_PATH_MISSING",
                f"required archive path is missing: {relative}",
            )
    return candidate


def _cleanup_staging(
    staging: Path,
    destination: Path,
    *,
    published: bool,
    active_error: BaseException | None,
) -> None:
    try:
        if staging.exists():
            shutil.rmtree(staging)
    except OSError as cleanup_exc:
        note = f"staging cleanup failed: {type(cleanup_exc).__name__}"
        if active_error is None:
            raise ArchiveMaterializationError(
                "STAGING_CLEANUP_FAILED", note
            ) from cleanup_exc
        active_error.add_note(note)
    if not published and destination.is_symlink():
        drift = ArchiveMaterializationError(
            "DESTINATION_DRIFT",
            f"destination became a symlink during materialization: {destination}",
        )
        if active_error is None:
            raise drift
        active_error.add_note(str(drift))


class SafeTarArchiveMaterializer(
    ArchiveMaterializationPort,
    MaterializedTreeInspectionPort,
):
    """Fail-closed tar materializer with bounded, atomic tree publication."""

    def inspect(self, root: str) -> MaterializedTreeInspection:
        tree_sha256, file_count, expanded_size = digest_materialized_tree(root)
        return MaterializedTreeInspection(tree_sha256, file_count, expanded_size)

    def materialize(
        self,
        request: ArchiveMaterializationRequest,
    ) -> ArchiveMaterializationResult:
        archive_path = Path(request.archive_path).resolve()
        destination = Path(request.destination).resolve()
        if not archive_path.is_file():
            raise ArchiveMaterializationError(
                "ARCHIVE_MISSING", f"archive is missing: {archive_path}"
            )
        if destination.exists() or destination.is_symlink():
            raise ArchiveMaterializationError(
                "DESTINATION_EXISTS",
                f"materialization destination already exists: {destination}",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", dir=str(destination.parent))
        )
        published = False
        try:
            with tarfile.open(archive_path, mode="r:*") as archive:
                plan = plan_tar_archive(
                    archive,
                    max_members=request.max_members,
                    max_expanded_size=request.max_expanded_size,
                )
                extract_tar_plan(archive, plan, staging)

            candidate = _validated_candidate(
                staging,
                plan.top_level,
                request.required_relative_paths,
            )
            tree_sha256, _, _ = digest_materialized_tree(candidate)
            verified_sha256, file_count, actual_size = _publish_tree(
                candidate, destination, tree_sha256
            )
            published = True
            return ArchiveMaterializationResult(
                str(destination),
                plan.top_level,
                verified_sha256,
                file_count,
                actual_size,
            )
        except ArchiveMaterializationError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise ArchiveMaterializationError(
                "MATERIALIZATION_FAILED",
                f"materialization provider failed: {type(exc).__name__}",
            ) from exc
        finally:
            _cleanup_staging(
                staging,
                destination,
                published=published,
                active_error=sys.exc_info()[1],
            )

__all__ = ["SafeTarArchiveMaterializer", "digest_materialized_tree"]
