from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from noetrium_platform.foundation.scope.api import ScopeIdentity


class ModelAssetMode(StrEnum):
    REFERENCE = "reference"
    COPY = "copy"
    MOVE = "move"
    SYMLINK = "symlink"
    FETCHED = "fetched"


@dataclass(frozen=True, slots=True)
class ModelSourceSpec:
    backend: str
    source: str
    revision: str | None = None
    storage_pool: str = "default"
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    resume: bool = True
    max_workers: int | None = None

    def __post_init__(self) -> None:
        if self.max_workers is not None and self.max_workers <= 0:
            raise ValueError("max_workers must be positive when provided")


@dataclass(frozen=True, slots=True)
class ModelAcquisitionReceipt:
    model_id: str
    backend: str
    source: str
    path: Path
    revision: str | None = None
    storage_pool: str = "default"


@dataclass(frozen=True, slots=True)
class ModelAssetOrigin:
    backend: str
    source: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class ManagedModelAsset:
    model_id: str
    scope: ScopeIdentity
    path: Path
    mode: ModelAssetMode = ModelAssetMode.REFERENCE
    family: str = ""
    notes: str = ""
    origin: ModelAssetOrigin | None = None
    tags: tuple[str, ...] = ()
    storage_pool: str | None = None


@dataclass(frozen=True, slots=True)
class ModelStoragePoolStatus:
    pool_id: str
    path: Path
    total_bytes: int
    used_bytes: int
    free_bytes: int


@dataclass(frozen=True, slots=True)
class ModelConfigSummary:
    model_id: str
    model_type: str | None = None
    architectures: tuple[str, ...] = ()
    torch_dtype: str | None = None
    max_position_embeddings: int | None = None
    quantization_method: str | None = None
    quantization_bits: int | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ModelAssetStats:
    model_id: str
    path: Path
    files: int
    directories: int
    bytes: int


@dataclass(frozen=True, slots=True)
class ModelAssetUsage:
    model_id: str
    deployment_ids: tuple[str, ...]
    desired_running_deployment_ids: tuple[str, ...]


__all__ = [
    "ManagedModelAsset", "ModelAcquisitionReceipt", "ModelAssetMode", "ModelAssetOrigin",
    "ModelAssetStats", "ModelAssetUsage", "ModelConfigSummary", "ModelSourceSpec", "ModelStoragePoolStatus",
]
