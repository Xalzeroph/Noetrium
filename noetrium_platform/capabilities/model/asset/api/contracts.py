from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from noetrium_platform.substrate.api import ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
    durable_carrier_closure_complete,
    durable_carrier_gc_eligible,
    validate_durable_carrier_closures,
)


@dataclass(frozen=True, slots=True)
class ModelAssetGcAssessment:
    model_id: str
    asset_digest: str
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.model_id) is not str or not self.model_id.strip():
            raise ValueError("model asset GC model_id must be canonical non-empty text")
        if (
            type(self.asset_digest) is not str
            or len(self.asset_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.asset_digest)
        ):
            raise ValueError("model asset GC asset_digest must be lowercase sha256")
        validate_durable_carrier_closures(self.closures)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "model.asset-gc-assessment.v1",
                    "model_id": self.model_id,
                    "asset_digest": self.asset_digest,
                    "closures": [
                        {
                            "authority": value.authority.value,
                            "proof_digest": value.proof_digest,
                            "retained_reference_ids": list(value.retained_reference_ids),
                        }
                        for value in self.closures
                    ],
                }
            ),
        )

    @property
    def closure_complete(self) -> bool:
        return durable_carrier_closure_complete(self.closures)

    @property
    def eligible(self) -> bool:
        return durable_carrier_gc_eligible(self.closures)


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
    "ManagedModelAsset", "ModelAcquisitionReceipt",
    "ModelAssetGcAssessment", "ModelAssetMode", "ModelAssetOrigin",
    "ModelAssetStats", "ModelAssetUsage", "ModelConfigSummary", "ModelSourceSpec", "ModelStoragePoolStatus",
]
