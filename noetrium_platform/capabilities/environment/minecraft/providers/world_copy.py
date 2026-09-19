from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .world_cut_integrity import (
    EXCLUDED_DIRECTORIES,
    EXCLUDED_FILES,
    MinecraftWorldCutError,
    copy_ignore,
)


class MinecraftWorldCopier(Protocol):
    def copy(self, source: Path, destination: Path) -> None: ...


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
    """Replaceable local copier; the provider owns correctness, not speed policy."""

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


class ReflinkMinecraftWorldCopier:
    """POSIX reflink copier with explicit observable fallback policy."""

    def __init__(
        self,
        *,
        cp_executable: str | None = None,
        runner: MinecraftWorldCopyCommandRunner | None = None,
        platform_name: str | None = None,
        fallback_copier: MinecraftWorldCopier | None = None,
        fallback_reporter: Callable[[str], None] | None = None,
    ) -> None:
        self.cp_executable = cp_executable
        self.runner = runner or subprocess.run
        self.platform_name = platform_name or os.name
        self.fallback_copier = fallback_copier
        self.fallback_reporter = fallback_reporter
        self.fallback_report_failures: list[str] = []

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
            lowered = detail.casefold()
            capability_failure = any(
                marker in lowered
                for marker in (
                    "operation not supported",
                    "invalid cross-device link",
                    "reflink",
                )
            )
            if self.fallback_copier is not None and capability_failure:
                if destination.exists():
                    shutil.rmtree(destination)
                try:
                    self.fallback_copier.copy(source, destination)
                except BaseException as exc:
                    raise MinecraftWorldCutError(
                        "REFLINK_FALLBACK_FAILED",
                        f"reflink={detail}; fallback={type(exc).__name__}: {exc}",
                    ) from exc
                if self.fallback_reporter is not None:
                    try:
                        self.fallback_reporter(detail)
                    except BaseException as exc:
                        self.fallback_report_failures.append(
                            f"{type(exc).__name__}: {exc}"
                        )
                return
            raise MinecraftWorldCutError(
                "REFLINK_COPY_FAILED",
                f"returncode={result.returncode}; detail={detail}",
            )
        if not destination.is_dir():
            raise MinecraftWorldCutError(
                "REFLINK_COPY_OUTPUT_MISSING", str(destination)
            )
        self._remove_volatile(destination)


__all__ = [
    "FilesystemMinecraftWorldCopier",
    "MinecraftWorldCopier",
    "ReflinkMinecraftWorldCopier",
]
