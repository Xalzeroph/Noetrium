from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import tarfile

from ..api.materialization import ArchiveMaterializationError


@dataclass(frozen=True, slots=True)
class TarMemberPlan:
    member: tarfile.TarInfo
    path: PurePosixPath
    key: str
    symlink_target: str | None = None
    hardlink_source: PurePosixPath | None = None


@dataclass(frozen=True, slots=True)
class TarArchivePlan:
    top_level: str
    members: tuple[TarMemberPlan, ...]
    expanded_size: int


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or any(part in ("", "..") for part in path.parts)
    ):
        raise ArchiveMaterializationError(
            "UNSAFE_MEMBER_PATH", f"unsafe archive member: {name!r}"
        )
    return path


def _safe_symlink_target(member_path: PurePosixPath, link_name: str) -> str:
    normalized = link_name.replace("\\", "/")
    target = PurePosixPath(normalized)
    if not normalized or "\x00" in normalized or target.is_absolute():
        raise ArchiveMaterializationError(
            "UNSAFE_LINK_TARGET",
            f"unsafe link target for {member_path}: {link_name!r}",
        )
    stack = list(member_path.parent.parts)
    for part in target.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if len(stack) <= 1:
                raise ArchiveMaterializationError(
                    "UNSAFE_LINK_TARGET",
                    f"link target escapes the single archive root for {member_path}: {link_name!r}",
                )
            stack.pop()
        else:
            stack.append(part)
    return normalized


def _safe_hardlink_target(link_name: str) -> PurePosixPath:
    normalized = link_name.replace("\\", "/")
    target = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or target.is_absolute()
        or any(part in ("", "..") for part in target.parts)
    ):
        raise ArchiveMaterializationError(
            "UNSAFE_LINK_TARGET",
            f"unsafe archive-root-relative hardlink target: {link_name!r}",
        )
    return target


def _validate_symlink_parents(paths: dict[str, tuple[tarfile.TarInfo, PurePosixPath]]) -> None:
    symlink_keys = {key for key, (member, _) in paths.items() if member.issym()}
    if not symlink_keys:
        return
    for key, (_, path) in paths.items():
        for depth in range(1, len(path.parts)):
            prefix = PurePosixPath(*path.parts[:depth]).as_posix()
            if prefix in symlink_keys:
                raise ArchiveMaterializationError(
                    "SYMLINK_PARENT",
                    f"archive member {key!r} is nested below symlink {prefix!r}",
                )


def _resolve_hardlinks(
    paths: dict[str, tuple[tarfile.TarInfo, PurePosixPath]],
) -> dict[str, PurePosixPath]:
    """Resolve hardlinks iteratively so untrusted chains cannot exhaust Python recursion."""

    cache: dict[str, PurePosixPath] = {}
    resolved: dict[str, PurePosixPath] = {}
    for start_key, (start_member, _) in paths.items():
        if not start_member.islnk():
            continue
        cached = cache.get(start_key)
        if cached is not None:
            resolved[start_key] = cached
            continue

        trail: list[str] = []
        seen: set[str] = set()
        key = start_key
        while True:
            cached = cache.get(key)
            if cached is not None:
                source = cached
                break
            if key in seen:
                raise ArchiveMaterializationError(
                    "HARDLINK_CYCLE", f"hardlink cycle includes {key!r}"
                )
            seen.add(key)
            trail.append(key)
            entry = paths.get(key)
            if entry is None:
                raise ArchiveMaterializationError(
                    "HARDLINK_TARGET_INVALID", f"hardlink target is missing: {key}"
                )
            member, path = entry
            if member.isreg():
                source = path
                break
            if not member.islnk():
                raise ArchiveMaterializationError(
                    "HARDLINK_TARGET_INVALID",
                    f"hardlink target is not a regular file or hardlink: {key}",
                )
            target = _safe_hardlink_target(member.linkname)
            key = target.as_posix().rstrip("/")

        for visited in trail:
            cache[visited] = source
        resolved[start_key] = source
    return resolved


def plan_tar_archive(
    archive: tarfile.TarFile,
    *,
    max_members: int,
    max_expanded_size: int,
) -> TarArchivePlan:
    members = archive.getmembers()
    if not members or len(members) > max_members:
        raise ArchiveMaterializationError(
            "MEMBER_LIMIT", f"archive member count is outside 1..{max_members}"
        )

    paths: dict[str, tuple[tarfile.TarInfo, PurePosixPath]] = {}
    expanded_size = 0
    for member in members:
        member_path = _safe_member_path(member.name)
        key = member_path.as_posix().rstrip("/")
        if key in paths:
            raise ArchiveMaterializationError(
                "DUPLICATE_MEMBER", f"duplicate archive member: {key}"
            )
        if not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
            raise ArchiveMaterializationError(
                "UNSUPPORTED_MEMBER_TYPE",
                f"unsupported archive member type: {member.name}",
            )
        if member.isreg():
            if member.size < 0:
                raise ArchiveMaterializationError("MEMBER_SIZE_INVALID", member.name)
            expanded_size += member.size
            if expanded_size > max_expanded_size:
                raise ArchiveMaterializationError(
                    "EXPANDED_SIZE_LIMIT",
                    f"archive expands beyond limit={max_expanded_size}",
                )
        paths[key] = (member, member_path)
    roots = {path.parts[0] for _, path in paths.values() if path.parts}
    if len(roots) != 1:
        raise ArchiveMaterializationError(
            "TOP_LEVEL_LAYOUT", "archive must contain exactly one top-level directory"
        )
    top_level = next(iter(roots))
    top_entry = paths.get(top_level)
    if top_entry is not None and not top_entry[0].isdir():
        raise ArchiveMaterializationError(
            "TOP_LEVEL_LAYOUT", "archive top-level entry must be a directory"
        )

    _validate_symlink_parents(paths)
    hardlink_sources = _resolve_hardlinks(paths)
    for source_path in hardlink_sources.values():
        source_key = source_path.as_posix().rstrip("/")
        source_member = paths[source_key][0]
        expanded_size += source_member.size
        if expanded_size > max_expanded_size:
            raise ArchiveMaterializationError(
                "EXPANDED_SIZE_LIMIT",
                f"archive logical materialization exceeds limit={max_expanded_size}",
            )
    planned: list[TarMemberPlan] = []
    for key, (member, path) in paths.items():
        symlink_target = _safe_symlink_target(path, member.linkname) if member.issym() else None
        planned.append(
            TarMemberPlan(
                member=member,
                path=path,
                key=key,
                symlink_target=symlink_target,
                hardlink_source=hardlink_sources.get(key),
            )
        )
    return TarArchivePlan(top_level, tuple(planned), expanded_size)


__all__ = ["TarArchivePlan", "TarMemberPlan", "plan_tar_archive"]
