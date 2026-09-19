from __future__ import annotations

import hashlib
import json
import math
import platform as host_platform
import re
from dataclasses import asdict, dataclass

from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path


class RuntimeToolchainError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"runtime toolchain failed [{code}]: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class JavaRuntimePlatform:
    operating_system: str
    architecture: str

    def __post_init__(self) -> None:
        if self.operating_system not in {"linux"}:
            raise ValueError(
                f"unsupported Java runtime operating system: {self.operating_system}"
            )
        if self.architecture not in {"x64", "aarch64"}:
            raise ValueError(
                f"unsupported Java runtime architecture: {self.architecture}"
            )

    @property
    def identity(self) -> str:
        return f"{self.operating_system}-{self.architecture}"


def current_java_runtime_platform() -> JavaRuntimePlatform:
    system = host_platform.system().lower()
    machine = host_platform.machine().lower()
    architecture = {
        "x86_64": "x64",
        "amd64": "x64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(machine)
    if system != "linux" or architecture is None:
        raise RuntimeToolchainError(
            "PLATFORM_UNSUPPORTED",
            f"verified Java runtime acquisition does not support host {system}/{machine}",
        )
    return JavaRuntimePlatform("linux", architecture)


def parse_java_major(version_text: str) -> int:
    first = next(
        (line.strip() for line in version_text.splitlines() if line.strip()), ""
    )
    match = re.search(r'\b(?:version\s+)?"?(\d+)(?:\.|"|$)', first)
    if not match:
        raise RuntimeToolchainError(
            "JAVA_VERSION_INVALID",
            f"unrecognized Java version: {first or '<empty>'}",
        )
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class JavaRuntimeProvisioningRequest:
    feature_version: int
    platform: JavaRuntimePlatform
    archive_path: str
    destination: str
    receipt_path: str
    scope: ScopeIdentity
    producer_operation_id: str | None = None
    timeout_s: float = 180.0

    def __post_init__(self) -> None:
        if not 8 <= self.feature_version <= 100:
            raise ValueError("Java feature version must be between 8 and 100")
        for name, value in (
            ("archive_path", self.archive_path),
            ("destination", self.destination),
            ("receipt_path", self.receipt_path),
        ):
            if not is_absolute_target_path(value):
                raise ValueError(f"Java runtime {name} must be absolute")
        if not math.isfinite(float(self.timeout_s)) or self.timeout_s <= 0:
            raise ValueError("Java runtime acquisition timeout must be finite and positive")


@dataclass(frozen=True, slots=True)
class JavaRuntimeReceipt:
    provider_id: str
    feature_version: int
    semantic_version: str
    release_name: str
    operating_system: str
    architecture: str
    metadata_url: str
    source_url: str
    archive_path: str
    archive_sha256: str
    archive_size: int
    java_home: str
    java_executable: str
    java_executable_sha256: str
    materialized_tree_sha256: str
    materialized_file_count: int
    materialized_size: int
    java_major: int
    java_version_output_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.provider_id.strip()
            or not self.semantic_version.strip()
            or not self.release_name.strip()
        ):
            raise ValueError("Java runtime receipt identity is incomplete")
        if not 8 <= self.feature_version <= 100:
            raise ValueError("Java runtime receipt feature version is invalid")
        if len(self.semantic_version) > 128 or len(self.release_name) > 256:
            raise ValueError("Java runtime receipt release identity is unbounded")
        JavaRuntimePlatform(self.operating_system, self.architecture)
        if self.java_major < self.feature_version:
            raise ValueError(
                "Java runtime receipt major version is below the requested feature"
            )
        if (
            self.archive_size <= 0
            or self.materialized_file_count <= 0
            or self.materialized_size <= 0
        ):
            raise ValueError("Java runtime receipt sizes must be positive")
        for value in (self.archive_path, self.java_home, self.java_executable):
            if not is_absolute_target_path(value):
                raise ValueError("Java runtime receipt paths must be absolute")
        for name, value in (
            ("archive_sha256", self.archive_sha256),
            ("java_executable_sha256", self.java_executable_sha256),
            ("materialized_tree_sha256", self.materialized_tree_sha256),
            ("java_version_output_sha256", self.java_version_output_sha256),
        ):
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ValueError(
                    f"Java runtime receipt {name} must be a lowercase SHA-256"
                )

    def digest(self) -> str:
        payload = json.dumps(
            asdict(self),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class JavaRuntimeProvisioningResult:
    receipt: JavaRuntimeReceipt
    archive_downloaded: bool
    materialized: bool


__all__ = [
    "JavaRuntimePlatform",
    "JavaRuntimeProvisioningRequest",
    "JavaRuntimeProvisioningResult",
    "JavaRuntimeReceipt",
    "RuntimeToolchainError",
    "current_java_runtime_platform",
    "parse_java_major",
]
