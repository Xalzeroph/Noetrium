from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.model.serving.api import (
    QualifiedDeploymentManifest,
    RoleModelManifest,
    RuntimeCanaryEvidence,
    RuntimeQualificationReceipt,
)

from .contracts import ModelEndpointRoute


def _require_digest(value: str, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _required_tuple(value: object, field: str) -> tuple:
    if type(value) is not tuple or not value:
        raise TypeError(f"qualified closure publication {field} must be a non-empty tuple")
    return value


@dataclass(frozen=True, slots=True)
class QualifiedModelClosurePublication:
    role_manifest: RoleModelManifest
    deployments: tuple[QualifiedDeploymentManifest, ...]
    routes: tuple[ModelEndpointRoute, ...]
    runtime_manifest_digest: str
    runtime_qualification_receipts: tuple[RuntimeQualificationReceipt, ...]
    runtime_canary_evidence: tuple[RuntimeCanaryEvidence, ...]
    runtime_qualification_root: str = "qualification"
    runtime_canary_root: str = "canary"

    def __post_init__(self) -> None:
        _required_tuple(self.deployments, "deployments")
        _required_tuple(self.routes, "routes")
        _required_tuple(self.runtime_qualification_receipts, "runtime receipts")
        _required_tuple(self.runtime_canary_evidence, "runtime canary evidence")
        _require_digest(self.runtime_manifest_digest, "runtime_manifest_digest")
        for field in ("runtime_qualification_root", "runtime_canary_root"):
            value = getattr(self, field)
            if type(value) is not str or not value.strip():
                raise TypeError(f"qualified closure publication {field} is required")


@dataclass(frozen=True, slots=True)
class QualifiedModelClosurePublicationReceipt:
    closure_path: str
    closure_digest: str
    runtime_evidence_paths: tuple[str, ...]
    runtime_canary_evidence_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.closure_path) is not str or not self.closure_path.strip():
            raise ValueError("qualified closure publication receipt requires a path")
        _require_digest(self.closure_digest, "closure_digest")
        for field in ("runtime_evidence_paths", "runtime_canary_evidence_paths"):
            paths = getattr(self, field)
            if type(paths) is not tuple or not paths:
                raise TypeError(f"qualified closure publication receipt requires {field}")
            if any(type(path) is not str or not path.strip() for path in paths):
                raise TypeError(f"qualified closure publication receipt {field} must be non-empty strings")


__all__ = [
    "QualifiedModelClosurePublication",
    "QualifiedModelClosurePublicationReceipt",
]
