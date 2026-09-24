from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from noetrium_platform.substrate.api import ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest


class ModelAssetClosureAuthority(StrEnum):
    EXECUTION = "execution"
    EVIDENCE = "evidence"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class ModelAssetReferenceClosure:
    authority: ModelAssetClosureAuthority
    proof_digest: str
    retained_reference_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.authority) is not ModelAssetClosureAuthority:
            raise TypeError("model asset closure authority must be typed")
        if (
            type(self.proof_digest) is not str
            or len(self.proof_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.proof_digest)
        ):
            raise ValueError("model asset closure proof_digest must be lowercase sha256")
        if type(self.retained_reference_ids) is not tuple or any(
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            for value in self.retained_reference_ids
        ):
            raise TypeError("model asset retained references must be canonical text tuple")
        if self.retained_reference_ids != tuple(sorted(set(self.retained_reference_ids))):
            raise ValueError("model asset retained references must be unique sorted order")


@dataclass(frozen=True, slots=True)
class ModelAssetGcAssessment:
    model_id: str
    asset_digest: str
    closures: tuple[ModelAssetReferenceClosure, ...] = ()
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
        if type(self.closures) is not tuple or any(
            type(value) is not ModelAssetReferenceClosure for value in self.closures
        ):
            raise TypeError("model asset GC closures must be typed tuple")
        authorities = tuple(value.authority for value in self.closures)
        if authorities != tuple(sorted(set(authorities), key=lambda value: value.value)):
            raise ValueError("model asset GC closures must have unique canonical authority order")
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
        return tuple(value.authority for value in self.closures) == tuple(
            sorted(ModelAssetClosureAuthority, key=lambda value: value.value)
        )

    @property
    def eligible(self) -> bool:
        return self.closure_complete and all(
            not value.retained_reference_ids for value in self.closures
        )


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
    "ManagedModelAsset", "ModelAcquisitionReceipt", "ModelAssetClosureAuthority",
    "ModelAssetGcAssessment", "ModelAssetMode", "ModelAssetOrigin", "ModelAssetReferenceClosure",
    "ModelAssetStats", "ModelAssetUsage", "ModelConfigSummary", "ModelSourceSpec", "ModelStoragePoolStatus",
]
