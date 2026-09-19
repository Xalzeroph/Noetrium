from __future__ import annotations

import os
from pathlib import Path
import shutil
import tarfile

from ..api.materialization import ArchiveMaterializationError
from ._tar_plan import TarArchivePlan


def _target(staging: Path, parts: tuple[str, ...]) -> Path:
    return staging.joinpath(*parts)


def _usable_mode(member: tarfile.TarInfo) -> int:
    mode = member.mode & 0o777
    if member.isdir():
        return mode | 0o700
    if member.isreg():
        return mode | 0o400
    return mode


def extract_tar_plan(
    archive: tarfile.TarFile,
    plan: TarArchivePlan,
    staging: Path,
) -> None:
    directories: list[tuple[tarfile.TarInfo, Path]] = []
    for planned in plan.members:
        member = planned.member
        target = _target(staging, planned.path.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True, mode=0o755)
            directories.append((member, target))
            continue
        if not member.isreg():
            continue
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        source = archive.extractfile(member)
        if source is None:
            raise ArchiveMaterializationError(
                "MEMBER_READ_FAILED",
                f"regular archive member cannot be read: {member.name}",
            )
        with source, target.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if target.stat().st_size != member.size:
            raise ArchiveMaterializationError(
                "MEMBER_SIZE_MISMATCH",
                f"extracted member size differs from tar metadata: {member.name}",
            )
        target.chmod(_usable_mode(member))

    for planned in plan.members:
        member = planned.member
        if not (member.issym() or member.islnk()):
            continue
        target = _target(staging, planned.path.parts)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        if target.exists() or target.is_symlink():
            raise ArchiveMaterializationError(
                "LINK_COLLISION",
                f"archive link collides with an extracted entry: {member.name}",
            )
        if member.issym():
            assert planned.symlink_target is not None
            target.symlink_to(planned.symlink_target)
            continue
        source_path = planned.hardlink_source
        if source_path is None:
            raise ArchiveMaterializationError(
                "HARDLINK_TARGET_INVALID",
                f"hardlink has no resolved regular-file source: {member.name}",
            )
        hardlink_path = _target(staging, source_path.parts)
        if not hardlink_path.is_file() or hardlink_path.is_symlink():
            raise ArchiveMaterializationError(
                "HARDLINK_TARGET_INVALID",
                f"resolved hardlink source is not an extracted regular file: {source_path}",
            )
        os.link(hardlink_path, target)

    for member, target in sorted(
        directories,
        key=lambda row: len(row[1].parts),
        reverse=True,
    ):
        target.chmod(_usable_mode(member))


__all__ = ["extract_tar_plan"]
