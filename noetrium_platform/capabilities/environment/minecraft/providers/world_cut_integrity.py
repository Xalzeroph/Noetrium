from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import JsonObject, canonical_digest
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path


EXCLUDED_DIRECTORIES = frozenset({"logs", "crash-reports"})
EXCLUDED_FILES = frozenset({"session.lock"})


class MinecraftWorldCutError(RuntimeError):
    """A world-cut or branch operation failed with a stable cause code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft world cut failed [{code}]: {message}")
        self.code = code


def safe_exception_message(exc: BaseException) -> str:
    descriptor = describe_exception(exc)
    return f"{descriptor.error_type}[{descriptor.error_digest[:16]}]"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_path(value: str, *, field: str) -> Path:
    path = Path(value).expanduser().resolve(strict=False)
    if not is_absolute_target_path(path):
        raise MinecraftWorldCutError(
            "PATH_NOT_ABSOLUTE", f"{field} is not absolute: {value!r}"
        )
    return path


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def safe_child(path: Path, root: Path, *, field: str) -> Path:
    resolved = path.resolve(strict=False)
    if resolved == root or not within(resolved, root):
        raise MinecraftWorldCutError(
            "PATH_OUTSIDE_PROVIDER_ROOT",
            f"{field} must be a strict child of {root}: {resolved}",
        )
    return resolved


def excluded(relative: Path) -> bool:
    return bool(
        EXCLUDED_FILES.intersection({relative.name})
        or EXCLUDED_DIRECTORIES.intersection(set(relative.parts))
    )


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in EXCLUDED_DIRECTORIES or name in EXCLUDED_FILES
    }


def validate_source(source: Path, level_name: str) -> None:
    if not source.is_dir():
        raise MinecraftWorldCutError("SOURCE_WORKDIR_MISSING", str(source))
    level = source / level_name
    if not level.is_dir():
        raise MinecraftWorldCutError("SOURCE_LEVEL_MISSING", str(level))
    if not (level / "level.dat").is_file():
        raise MinecraftWorldCutError(
            "SOURCE_LEVEL_DAT_MISSING", str(level / "level.dat")
        )


def tree_manifest(root: Path) -> tuple[dict[str, JsonValue], ...]:
    files: list[tuple[str, int, Path]] = []

    def _walk_error(exc: OSError) -> None:
        raise MinecraftWorldCutError(
            "WORLD_SCAN_FAILED", f"{root}: {type(exc).__name__}: {exc}"
        ) from exc

    for current, directories, names in os.walk(
        root, topdown=True, followlinks=False, onerror=_walk_error
    ):
        current_path = Path(current)
        directories.sort()
        names.sort()
        for name in tuple(directories):
            child = current_path / name
            relative = child.relative_to(root)
            if excluded(relative):
                directories.remove(name)
                continue
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise MinecraftWorldCutError("SYMLINK_UNSUPPORTED", str(child))
            if not stat.S_ISDIR(mode):
                raise MinecraftWorldCutError("UNSUPPORTED_FILE_TYPE", str(child))
        for name in names:
            child = current_path / name
            relative = child.relative_to(root)
            if excluded(relative):
                continue
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise MinecraftWorldCutError("SYMLINK_UNSUPPORTED", str(child))
            if not stat.S_ISREG(info.st_mode):
                raise MinecraftWorldCutError("UNSUPPORTED_FILE_TYPE", str(child))
            files.append((relative.as_posix(), info.st_size, child))

    rows = tuple(
        {"path": relative, "size": size, "sha256": sha256_file(path)}
        for relative, size, path in sorted(files, key=lambda item: item[0])
    )
    if not rows:
        raise MinecraftWorldCutError("SOURCE_EMPTY", str(root))
    return rows


def manifest_digest(manifest: tuple[dict[str, JsonValue], ...]) -> str:
    return canonical_digest(manifest)


def metadata_bytes(value: JsonObject) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def file_ref(path: Path) -> str:
    return f"file:{path}"


def path_from_ref(value: str) -> Path:
    if not value.startswith("file:"):
        raise MinecraftWorldCutError("SNAPSHOT_REF_UNSUPPORTED", value)
    return local_path(value[5:], field="snapshot_ref")


def validated_manifest(
    value: object, *, source: str
) -> tuple[dict[str, JsonValue], ...]:
    """Decode the content manifest without allowing ambiguous JSON shapes."""

    if not isinstance(value, list):
        raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_SHAPE", source)
    rows: list[dict[str, JsonValue]] = []
    paths: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_ROW", source)
        relative = row.get("path")
        size = row.get("size")
        digest = row.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or relative in paths
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest.lower())
        ):
            raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_ROW", source)
        paths.add(relative)
        rows.append({"path": relative, "size": size, "sha256": digest.lower()})
    if not rows:
        raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_EMPTY", source)
    return tuple(rows)
