from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path
from noetrium_platform.foundation.kernel.kernel.durability import durable_create_binary_file
from typing import Protocol

from .world_cut_integrity import (
    EXCLUDED_DIRECTORIES,
    EXCLUDED_FILES,
    MinecraftWorldCutError,
    copy_ignore,
    excluded,
    tree_manifest,
)


class MinecraftWorldCopier(Protocol):
    def copy(self, source: Path, destination: Path) -> None: ...

    def copy_with_manifest(
        self,
        source: Path,
        destination: Path,
    ) -> tuple[dict[str, object], ...]: ...


class MinecraftWorldCopyCommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]: ...


class FilesystemMinecraftWorldCopier:
    """Local copier with one-pass content-addressed publication support."""

    _STREAM_CHUNK_BYTES = 4 * 1024 * 1024

    def copy(self, source: Path, destination: Path) -> None:
        if destination.exists():
            raise MinecraftWorldCutError("DESTINATION_ALREADY_EXISTS", str(destination))
        try:
            shutil.copytree(source, destination, ignore=copy_ignore)
        except Exception as exc:
            raise MinecraftWorldCutError(
                "WORLD_COPY_FAILED",
                f"{source} -> {destination}: {type(exc).__name__}: {exc}",
            ) from exc

    def copy_with_manifest(
        self,
        source: Path,
        destination: Path,
    ) -> tuple[dict[str, object], ...]:
        """Copy once while deriving the exact content manifest.

        The source world is quiescent before publication. Every destination byte
        is written from the exact source chunk that updates the SHA-256 digest,
        so a second full-tree target read cannot add information to the
        publication proof. The atomic template marker remains the commit point.
        """

        if destination.exists():
            raise MinecraftWorldCutError(
                "DESTINATION_ALREADY_EXISTS", str(destination)
            )
        if not source.is_dir():
            raise MinecraftWorldCutError("SOURCE_LEVEL_MISSING", str(source))

        rows: list[dict[str, object]] = []

        def walk_error(exc: OSError) -> None:
            raise MinecraftWorldCutError(
                "WORLD_SCAN_FAILED",
                f"{source}: {type(exc).__name__}: {exc}",
            ) from exc

        try:
            destination.mkdir(parents=True)
            for current, directories, names in os.walk(
                source,
                topdown=True,
                followlinks=False,
                onerror=walk_error,
            ):
                current_path = Path(current)
                relative_dir = current_path.relative_to(source)
                destination_dir = destination / relative_dir
                directories.sort()
                names.sort()

                for name in tuple(directories):
                    child = current_path / name
                    relative = child.relative_to(source)
                    if excluded(relative):
                        directories.remove(name)
                        continue
                    info = child.lstat()
                    if stat.S_ISLNK(info.st_mode):
                        raise MinecraftWorldCutError(
                            "SYMLINK_UNSUPPORTED", str(child)
                        )
                    if not stat.S_ISDIR(info.st_mode):
                        raise MinecraftWorldCutError(
                            "UNSUPPORTED_FILE_TYPE", str(child)
                        )
                    (destination / relative).mkdir(
                        mode=stat.S_IMODE(info.st_mode),
                        exist_ok=False,
                    )

                for name in names:
                    child = current_path / name
                    relative = child.relative_to(source)
                    if excluded(relative):
                        continue
                    info = child.lstat()
                    if stat.S_ISLNK(info.st_mode):
                        raise MinecraftWorldCutError(
                            "SYMLINK_UNSUPPORTED", str(child)
                        )
                    if not stat.S_ISREG(info.st_mode):
                        raise MinecraftWorldCutError(
                            "UNSUPPORTED_FILE_TYPE", str(child)
                        )

                    target = destination / relative
                    digest = hashlib.sha256()
                    copied = 0
                    with child.open("rb", buffering=0) as reader, durable_create_binary_file(
                        target, buffering=0
                    ) as writer:
                        while True:
                            chunk = reader.read(self._STREAM_CHUNK_BYTES)
                            if not chunk:
                                break
                            digest.update(chunk)
                            written = writer.write(chunk)
                            if written != len(chunk):
                                raise MinecraftWorldCutError(
                                    "WORLD_COPY_SHORT_WRITE",
                                    f"{child} -> {target}: "
                                    f"{written}/{len(chunk)}",
                                )
                            copied += written
                    if copied != info.st_size:
                        raise MinecraftWorldCutError(
                            "WORLD_COPY_SIZE_DRIFT",
                            f"{child}: source={info.st_size} copied={copied}",
                        )
                    os.chmod(target, stat.S_IMODE(info.st_mode))
                    rows.append(
                        {
                            "path": relative.as_posix(),
                            "size": copied,
                            "sha256": digest.hexdigest(),
                        }
                    )

            rows.sort(key=lambda row: str(row["path"]))
            if not rows:
                raise MinecraftWorldCutError("SOURCE_EMPTY", str(source))
            return tuple(rows)
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise


class ReflinkMinecraftWorldCopier:
    """POSIX reflink copier with strict fail-closed semantics."""

    def __init__(
        self,
        *,
        cp_executable: str | None = None,
        runner: MinecraftWorldCopyCommandRunner | None = None,
        platform_name: str | None = None,
    ) -> None:
        self.cp_executable = cp_executable
        self.runner = runner or subprocess.run
        self.platform_name = platform_name or os.name

    @staticmethod
    def _remove_volatile(destination: Path) -> None:
        for current, directories, files in os.walk(destination, topdown=True):
            current_path = Path(current)
            for name in tuple(directories):
                if name in EXCLUDED_DIRECTORIES:
                    shutil.rmtree(current_path / name)
                    directories.remove(name)
            for name in files:
                if name in EXCLUDED_FILES:
                    (current_path / name).unlink(missing_ok=True)

    def copy(self, source: Path, destination: Path) -> None:
        if destination.exists():
            raise MinecraftWorldCutError("DESTINATION_ALREADY_EXISTS", str(destination))
        if self.platform_name != "posix":
            raise MinecraftWorldCutError(
                "REFLINK_UNSUPPORTED_PLATFORM",
                f"reflink copier requires POSIX target, got {self.platform_name}",
            )
        executable = self.cp_executable or shutil.which("cp")
        if not executable:
            raise MinecraftWorldCutError(
                "REFLINK_TOOL_MISSING", "cp executable is unavailable"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "-a",
            "--reflink=always",
            "--",
            f"{source}/.",
            str(destination),
        ]
        try:
            result = self.runner(
                command, capture_output=True, text=True, check=False
            )
        except OSError as exc:
            raise MinecraftWorldCutError(
                "REFLINK_COPY_LAUNCH_FAILED",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or "<no cp output>").strip()[-2048:]
            if destination.exists():
                shutil.rmtree(destination)
            raise MinecraftWorldCutError(
                "REFLINK_COPY_FAILED",
                f"returncode={result.returncode}; detail={detail}",
            )
        if not destination.is_dir():
            raise MinecraftWorldCutError(
                "REFLINK_COPY_OUTPUT_MISSING", str(destination)
            )
        self._remove_volatile(destination)

    def copy_with_manifest(
        self,
        source: Path,
        destination: Path,
    ) -> tuple[dict[str, object], ...]:
        self.copy(source, destination)
        return tuple(tree_manifest(destination))


__all__ = [
    "FilesystemMinecraftWorldCopier",
    "MinecraftWorldCopier",
    "ReflinkMinecraftWorldCopier",
]
