from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol



@dataclass(frozen=True, slots=True)
class ServiceCapturePaths:
    stdout_path: Path
    stderr_path: Path
    stdout_ref: str
    stderr_ref: str

    def __post_init__(self) -> None:
        for path in (self.stdout_path, self.stderr_path):
            if not is_absolute_target_path(path):
                raise ValueError("service capture paths must be absolute")
        if not self.stdout_ref or not self.stderr_ref:
            raise ValueError("service capture refs required")


class ServiceCapturePathProvider(Protocol):
    def paths(self, contract: ServiceLaunchContract) -> ServiceCapturePaths: ...


class DirectoryCapturePathProvider:
    """Deterministically assigns raw stdout/stderr files by service+generation."""

    def __init__(self, root: Path) -> None:
        root = root.resolve()
        if not is_absolute_target_path(root):
            raise ValueError("capture root must resolve to an absolute path")
        self.root = root

    def paths(self, contract: ServiceLaunchContract) -> ServiceCapturePaths:
        safe_service = contract.service_id.replace("/", "_")
        safe_generation = contract.generation.replace("/", "_")
        root = self.root / safe_service / safe_generation
        stdout = root / "stdout.log"
        stderr = root / "stderr.log"
        return ServiceCapturePaths(stdout, stderr, f"file:{stdout}", f"file:{stderr}")


__all__ = ["DirectoryCapturePathProvider", "ServiceCapturePathProvider", "ServiceCapturePaths"]
