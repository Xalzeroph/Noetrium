from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.asset.api import (
    ManagedModelAsset,
    ModelAssetMode,
    ModelAssetOrigin,
    ModelAssetUsage,
    ModelSourceSpec,
)
from noetrium_platform.capabilities.model.asset.catalog.model_source_catalog import (
    ModelSourceCatalogEntry,
)
from noetrium_platform.composition.model_stack_materialization import (
    DockerModelStackMaterializer,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE


class _Catalog:
    def resolve(self, model_id: str) -> ModelSourceCatalogEntry:
        return ModelSourceCatalogEntry(
            model_id=model_id,
            source=ModelSourceSpec(
                backend="huggingface",
                source="Qwen/Qwen3-8B",
                revision="rev",
            ),
            family="qwen3",
            tags=("auto-source", "formal"),
        )


class _Assets:
    def __init__(self, asset):
        self.asset = asset
        self.promoted = 0
        self.fetched = 0
        self.unregistered = 0

    def model(self, model_id: str):
        if self.asset is None:
            raise FileNotFoundError(model_id)
        return self.asset

    def model_usage(self, model_id: str) -> ModelAssetUsage:
        return ModelAssetUsage(model_id, (), ())

    def materialize_reference_from_source(self, model_id, scope, spec, **kwargs):
        self.promoted += 1
        self.asset = ManagedModelAsset(
            model_id, scope, Path("/managed/Qwen3-8B"), ModelAssetMode.FETCHED,
            kwargs.get("family", ""), "",
            ModelAssetOrigin(spec.backend, spec.source, spec.revision),
            tuple(kwargs.get("tags", ())), "default",
        )
        return self.asset

    def fetch_model(self, model_id, scope, spec, **kwargs):
        self.fetched += 1
        self.asset = ManagedModelAsset(
            model_id, scope, Path("/managed/Qwen3-8B"), ModelAssetMode.FETCHED,
            kwargs.get("family", ""), "",
            ModelAssetOrigin(spec.backend, spec.source, spec.revision),
            tuple(kwargs.get("tags", ())), "default",
        )
        return self.asset

    def unregister_model(self, *args, **kwargs):
        self.unregistered += 1
        raise AssertionError("automatic stack recovery must never retire a reusable model identity")


def _materializer(assets: _Assets) -> DockerModelStackMaterializer:
    value = object.__new__(DockerModelStackMaterializer)
    value._assets = assets
    value._sources = _Catalog()
    return value


def test_inaccessible_reference_is_promoted_without_retirement(tmp_path: Path):
    missing = tmp_path / "missing-reference"
    assets = _Assets(
        ManagedModelAsset(
            "Qwen3-8B", PLATFORM_SCOPE, missing, ModelAssetMode.REFERENCE,
            "qwen3", "", ModelAssetOrigin("local-path", str(missing)),
            ("auto-source", "formal"), None,
        )
    )
    recovered = _materializer(assets)._ensure_asset("Qwen3-8B", scope=None)
    assert recovered.mode is ModelAssetMode.FETCHED
    assert assets.promoted == 1
    assert assets.fetched == 0
    assert assets.unregistered == 0


def test_inaccessible_managed_asset_fails_closed_without_retirement(tmp_path: Path):
    missing = tmp_path / "missing-managed"
    assets = _Assets(
        ManagedModelAsset(
            "Qwen3-8B", PLATFORM_SCOPE, missing, ModelAssetMode.FETCHED,
            "qwen3", "", ModelAssetOrigin("huggingface", "Qwen/Qwen3-8B", "rev"),
            ("auto-source", "formal"), "default",
        )
    )
    with pytest.raises(RuntimeError, match="requires explicit recovery"):
        _materializer(assets)._ensure_asset("Qwen3-8B", scope=None)
    assert assets.promoted == 0
    assert assets.fetched == 0
    assert assets.unregistered == 0


def test_missing_model_fetches_without_retirement():
    assets = _Assets(None)
    recovered = _materializer(assets)._ensure_asset("Qwen3-8B", scope=None)
    assert recovered.mode is ModelAssetMode.FETCHED
    assert assets.fetched == 1
    assert assets.promoted == 0
    assert assets.unregistered == 0
