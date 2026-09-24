from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
from threading import RLock

from noetrium_platform.substrate.api import ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import DurableCarrierReferenceClosure

from noetrium_platform.capabilities.model.asset.api import (
    ManagedModelAsset,
    ModelAssetGcAssessment,
    ModelAssetMode,
    ModelAssetOrigin,
    ModelAssetStats,
    ModelAssetStoragePort,
    ModelAssetUsage,
    ModelConfigSummary,
    ModelSourceBackend,
    ModelSourceSpec,
    ModelStoragePoolStatus,
)

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentCatalogPort, ModelDesiredState

from .codec import encode_model_asset
from .registry import ModelAssetRegistry


class ModelAssetManager:
    def __init__(
        self,
        asset_registry: ModelAssetRegistry,
        references: ModelAssetReferencePort,
        storage: ModelAssetStoragePort,
        source_backends: tuple[ModelSourceBackend, ...],
    ) -> None:
        self._asset_registry = asset_registry
        self._references = references
        self._storage = storage
        self._source_backends = {backend.backend_id: backend for backend in source_backends}
        if len(self._source_backends) != len(source_backends):
            raise ValueError("duplicate model source backend")
        self._lock = RLock()

    def fetch_model(self, model_id: str, scope: ScopeIdentity, spec: ModelSourceSpec, *, family: str = "", notes: str = "", tags: tuple[str, ...] = ()) -> ManagedModelAsset:
        with self._lock:
            self._asset_registry.ensure_not_retired(model_id)
            try:
                self.model(model_id)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(
                    f"model is already registered: {model_id}"
                )
            try:
                backend = self._source_backends[spec.backend]
            except KeyError as exc:
                raise KeyError(
                    f"unknown model source backend: {spec.backend}"
                ) from exc
            receipt = backend.acquire(model_id, spec)
            return self._asset_registry.put(
                ManagedModelAsset(
                    model_id,
                    scope,
                    receipt.path,
                    ModelAssetMode.FETCHED,
                    family,
                    notes,
                    ModelAssetOrigin(
                        receipt.backend,
                        receipt.source,
                        receipt.revision,
                    ),
                    self._normalize_tags(tags),
                    receipt.storage_pool,
                )
            )

    def register_model(
        self, model_id: str, scope: ScopeIdentity, source: Path, *, mode: str = "reference", family: str = "",
        notes: str = "", tags: tuple[str, ...] = (), storage_pool: str = "default"
    ) -> ManagedModelAsset:
        with self._lock:
            self._asset_registry.ensure_not_retired(model_id)
            asset_mode = ModelAssetMode(mode)
            resolved_source = source.expanduser().resolve()
            path = self._storage.materialize(
                model_id,
                resolved_source,
                asset_mode,
                pool_id=storage_pool,
            )
            return self._asset_registry.put(
                ManagedModelAsset(
                    model_id,
                    scope,
                    path,
                    asset_mode,
                    family,
                    notes,
                    ModelAssetOrigin("local-path", str(resolved_source)),
                    self._normalize_tags(tags),
                    (
                        None
                        if asset_mode is ModelAssetMode.REFERENCE
                        else storage_pool
                    ),
                )
            )

    def model(self, model_id: str) -> ManagedModelAsset:
        return self._asset_registry.get(model_id)

    def models(self, *, tags: tuple[str, ...] = (), family: str | None = None) -> tuple[ManagedModelAsset, ...]:
        required = set(self._normalize_tags(tags))
        values = self._asset_registry.all()
        return tuple(
            value for value in values
            if (not required or required.issubset(value.tags))
            and (family is None or value.family == family)
        )

    def source_backends(self) -> tuple[str, ...]:
        return tuple(sorted(self._source_backends))

    def storage_pools(self) -> tuple[ModelStoragePoolStatus, ...]:
        return self._storage.pools()

    def model_stats(self, model_id: str) -> ModelAssetStats:
        asset = self.model(model_id)
        path = asset.path.resolve() if asset.path.is_symlink() else asset.path
        if not path.exists():
            return ModelAssetStats(model_id, path, 0, 0, 0)
        if path.is_file():
            return ModelAssetStats(model_id, path, 1, 0, path.stat().st_size)
        files = 0
        directories = 1
        total_bytes = 0
        for child in path.rglob("*"):
            if child.is_dir():
                directories += 1
            elif child.is_file():
                files += 1
                try:
                    total_bytes += child.stat().st_size
                except FileNotFoundError:
                    continue
        return ModelAssetStats(model_id, path, files, directories, total_bytes)

    def model_config(self, model_id: str) -> ModelConfigSummary | None:
        asset = self.model(model_id)
        root = asset.path.resolve() if asset.path.is_symlink() else asset.path
        config_path = root / "config.json" if root.is_dir() else root.parent / "config.json"
        if not config_path.exists():
            return None
        try:
            data = json.loads(config_path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return ModelConfigSummary(model_id=model_id, detail=f"config-unreadable:{type(exc).__name__}")
        if not isinstance(data, dict):
            return ModelConfigSummary(model_id=model_id, detail="config-not-object")
        quantization = data.get("quantization_config") or {}
        if not isinstance(quantization, dict):
            quantization = {}
        bits = quantization.get("bits")
        try:
            quantization_bits = int(bits) if bits is not None else None
        except (TypeError, ValueError):
            quantization_bits = None
        max_position = data.get("max_position_embeddings")
        try:
            max_position_embeddings = int(max_position) if max_position is not None else None
        except (TypeError, ValueError):
            max_position_embeddings = None
        return ModelConfigSummary(
            model_id=model_id,
            model_type=(str(data["model_type"]) if data.get("model_type") is not None else None),
            architectures=tuple(str(item) for item in data.get("architectures", ())),
            torch_dtype=(str(data["torch_dtype"]) if data.get("torch_dtype") is not None else None),
            max_position_embeddings=max_position_embeddings,
            quantization_method=(str(quantization["quant_method"]) if quantization.get("quant_method") is not None else None),
            quantization_bits=quantization_bits,
        )

    def model_usage(self, model_id: str) -> ModelAssetUsage:
        self.model(model_id)
        return ModelAssetUsage(
            model_id,
            tuple(sorted(self._references.references(model_id))),
            tuple(sorted(self._references.active_references(model_id))),
        )

    @staticmethod
    def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({str(tag).strip() for tag in tags if str(tag).strip()}))

    @staticmethod
    def _asset_digest(asset: ManagedModelAsset) -> str:
        return sha256(encode_model_asset(asset)).hexdigest()

    def assess_model_gc(
        self,
        model_id: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> ModelAssetGcAssessment:
        references = self._references.references(model_id)
        if references:
            raise RuntimeError(
                f"model is still referenced by a deployment: {model_id}"
            )
        retirement = self._asset_registry.retirement(model_id)
        if retirement is None:
            asset = self.model(model_id)
        else:
            asset, _durable_delete, _durable_gc_proof = retirement
            if asset is None:
                raise RuntimeError(
                    "model asset physical GC has already converged: "
                    f"{model_id}"
                )
        return ModelAssetGcAssessment(
            model_id=model_id,
            asset_digest=self._asset_digest(asset),
            closures=closures,
        )

    def _require_physical_gc(
        self,
        asset: ManagedModelAsset,
        gc: ModelAssetGcAssessment | None,
    ) -> ModelAssetGcAssessment:
        if type(gc) is not ModelAssetGcAssessment:
            raise RuntimeError(
                "managed model bytes require a typed model asset GC assessment"
            )
        if (
            gc.model_id != asset.model_id
            or gc.asset_digest != self._asset_digest(asset)
        ):
            raise RuntimeError(
                "model asset GC assessment does not bind the exact asset generation"
            )
        if not gc.eligible:
            raise RuntimeError(
                "managed model bytes require complete execution, evidence, and "
                "recovery closure with zero retained references"
            )
        return gc

    def unregister_model(
        self,
        model_id: str,
        *,
        delete_managed_files: bool = False,
        gc: ModelAssetGcAssessment | None = None,
    ) -> bool:
        if type(delete_managed_files) is not bool:
            raise TypeError("delete_managed_files must be bool")
        with self._lock:
            # This outer cross-process fence spans both deployment-reference
            # observation and retirement/physical cleanup. Deployment creation
            # holds the same fence through its durable desired-state commit.
            with self._asset_registry.lifecycle_fence(model_id):
                return self._unregister_model_fenced(
                    model_id,
                    delete_managed_files=delete_managed_files,
                    gc=gc,
                )

    def _unregister_model_fenced(
        self,
        model_id: str,
        *,
        delete_managed_files: bool,
        gc: ModelAssetGcAssessment | None,
    ) -> bool:
        references = self._references.references(model_id)
        if references:
            raise RuntimeError(
                f"model is still referenced by a deployment: {model_id}"
            )

        retirement = self._asset_registry.retirement(model_id)
        if retirement is None:
            asset = self.model(model_id)
            physical_gc = (
                self._require_physical_gc(asset, gc)
                if delete_managed_files
                else None
            )
            asset = self._asset_registry.begin_retirement(
                asset,
                delete_managed_files=delete_managed_files,
                gc_proof_digest=(
                    None if physical_gc is None else physical_gc.proof_digest
                ),
            )
            durable_delete = delete_managed_files
            durable_gc_proof = (
                None if physical_gc is None else physical_gc.proof_digest
            )
        else:
            asset, durable_delete, durable_gc_proof = retirement
            if asset is None:
                return True

            if durable_delete:
                physical_gc = self._require_physical_gc(asset, gc)
                if physical_gc.proof_digest != durable_gc_proof:
                    raise RuntimeError(
                        "model asset GC proof changed across retirement retry"
                    )
            elif delete_managed_files:
                physical_gc = self._require_physical_gc(asset, gc)
                asset = self._asset_registry.authorize_gc(
                    asset,
                    gc_proof_digest=physical_gc.proof_digest,
                )
                durable_delete = True
                durable_gc_proof = physical_gc.proof_digest
            else:
                physical_gc = None

        # The lifecycle fence is still held here, so no deployment admission
        # can cross this recheck or commit after it until retirement/GC
        # converges or fails.
        references = self._references.references(model_id)
        if references:
            raise RuntimeError(
                "model gained a deployment reference during retirement: "
                f"{model_id}"
            )

        if durable_delete:
            self._storage.remove(asset)
        return self._asset_registry.finish_retirement(asset)



__all__ = ["ModelAssetManager"]
