from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.request import Request

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind, ArtifactRecord, ArtifactRetention
from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path


@dataclass(frozen=True, slots=True)
class ArtifactAcquisitionRequest:
    """Reproducible request for acquiring one immutable artifact content file."""

    artifact_id: str
    source_url: str
    destination: str
    scope: ScopeIdentity
    kind: ArtifactKind
    producer_component_id: str
    producer_operation_id: str | None = None
    media_type: str = "application/octet-stream"
    retention: ArtifactRetention = ArtifactRetention.PROJECT
    expected_sha256: str | None = None
    expected_sha1: str | None = None
    expected_size: int | None = None
    replace_existing: bool = False
    timeout_s: float = 120.0

    def __post_init__(self) -> None:
        if not self.artifact_id.strip() or not self.producer_component_id.strip():
            raise ValueError("artifact acquisition identity is required")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("artifact source_url must use http or https")
        if not is_absolute_target_path(self.destination):
            raise ValueError("artifact destination must be absolute")
        if not self.media_type.strip():
            raise ValueError("artifact media_type must be non-empty")
        if self.timeout_s <= 0:
            raise ValueError("artifact acquisition timeout must be positive")
        if self.expected_size is not None and self.expected_size < 0:
            raise ValueError("artifact expected_size must be non-negative")
        for name, value, length in (
            ("expected_sha256", self.expected_sha256, 64),
            ("expected_sha1", self.expected_sha1, 40),
        ):
            if value is not None and (len(value) != length or any(c not in "0123456789abcdefABCDEF" for c in value)):
                raise ValueError(f"{name} must be a hexadecimal digest of length {length}")
        if self.expected_sha256 is None and self.expected_sha1 is None:
            raise ValueError("artifact acquisition requires a SHA-256 or SHA-1 expectation")


@dataclass(frozen=True, slots=True)
class ArtifactAcquisitionResult:
    record: ArtifactRecord
    storage_provider_id: str
    location: str
    downloaded: bool
    sha256: str
    sha1: str
    size: int

    def __post_init__(self) -> None:
        if not self.storage_provider_id.strip() or not self.location.strip():
            raise ValueError("artifact acquisition storage provider/location must be non-empty")
        for name, value, length in (("sha256", self.sha256, 64), ("sha1", self.sha1, 40)):
            if len(value) != length or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"artifact acquisition {name} must be lowercase hexadecimal")
        if self.record.digest != self.sha256:
            raise ValueError("artifact acquisition record digest must match verified SHA-256")
        if not isinstance(self.downloaded, bool):
            raise TypeError("artifact acquisition downloaded must be bool")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("artifact acquisition size must be a non-negative integer")


class ArtifactAcquisitionError(RuntimeError):
    """A content acquisition operation failed with a stable diagnostic code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"artifact acquisition failed [{code}]: {message}")
        self.code = code


class ArtifactHttpResponse(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


ArtifactHttpOpener = Callable[[Request, float], ArtifactHttpResponse]


class ArtifactAcquisitionPort(Protocol):
    """Content acquisition seam; catalog registration remains a separate authority."""

    def acquire(self, request: ArtifactAcquisitionRequest) -> ArtifactAcquisitionResult:
        ...


__all__ = [
    "ArtifactAcquisitionError",
    "ArtifactHttpOpener",
    "ArtifactHttpResponse",
    "ArtifactAcquisitionPort",
    "ArtifactAcquisitionRequest",
    "ArtifactAcquisitionResult",
]
