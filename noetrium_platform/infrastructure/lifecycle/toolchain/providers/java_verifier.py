from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from noetrium_platform.infrastructure.lifecycle.toolchain.api import RuntimeToolchainError, parse_java_major

JavaCommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class JavaExecutableVerification:
    major: int
    version_output: str
    executable_sha256: str


class JavaRuntimeVerifierPort(Protocol):
    def verify(
        self, java_executable: Path, feature_version: int
    ) -> JavaExecutableVerification: ...


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


class JavaRuntimeVerifier(JavaRuntimeVerifierPort):
    """Verify executable identity through filesystem checks and `java -version`."""

    def __init__(self, command_runner: JavaCommandRunner = subprocess.run) -> None:
        self._command_runner = command_runner

    def verify(
        self, java_executable: Path, feature_version: int
    ) -> JavaExecutableVerification:
        if (
            not java_executable.is_file()
            or java_executable.is_symlink()
            or not os.access(java_executable, os.X_OK)
        ):
            raise RuntimeToolchainError(
                "JAVA_EXECUTABLE_INVALID",
                f"materialized Java executable is missing, linked, or not executable: {java_executable}",
            )
        try:
            result = self._command_runner(
                [str(java_executable), "-version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            raise RuntimeToolchainError(
                "JAVA_COMMAND_FAILED", f"{type(exc).__name__}: {exc}"
            ) from exc
        output = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            raise RuntimeToolchainError(
                "JAVA_COMMAND_FAILED",
                f"java -version returned {result.returncode}: {output}",
            )
        major = parse_java_major(output)
        if major != feature_version:
            raise RuntimeToolchainError(
                "JAVA_VERSION_MISMATCH",
                f"materialized Java major is {major}; expected exactly {feature_version}",
            )
        executable_sha256, _ = sha256_file(java_executable)
        return JavaExecutableVerification(major, output, executable_sha256)


__all__ = [
    "JavaCommandRunner",
    "JavaExecutableVerification",
    "JavaRuntimeVerifier",
    "JavaRuntimeVerifierPort",
    "sha256_file",
]
