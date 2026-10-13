from __future__ import annotations

from collections import namedtuple

from noetrium_platform.capabilities.model.stack.runtime import (
    ModelArtifactClosureAuthority,
    ModelRuntimeAssetCache,
)
import noetrium_platform.capabilities.model.stack.runtime.runtime_asset_cache as cache_module


def _model_root(root):
    root.mkdir(parents=True)
    (root / "config.json").write_text(
        '{"model_type":"test","architectures":["Test"],'
        '"torch_dtype":"bfloat16","max_position_embeddings":4096}',
        encoding="utf-8",
    )
    (root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "model.safetensors").write_bytes(b"weights-v1")
    return root


def test_runtime_asset_cache_projects_one_verified_artifact_identity(tmp_path, monkeypatch):
    source = _model_root(tmp_path / "source")
    closure = ModelArtifactClosureAuthority().freeze(source)
    cache = ModelRuntimeAssetCache(tmp_path / "cache")
    monkeypatch.setattr(
        ModelRuntimeAssetCache,
        "_same_filesystem",
        staticmethod(lambda source, cache_root: False),
    )

    hot = cache.resolve(source, closure)
    assert hot != source
    assert hot.name == closure.digest()
    assert ModelArtifactClosureAuthority().freeze(hot) == closure

    # A corrupt disposable projection is discarded and rebuilt from truth.
    (hot / "config.json").write_text("{}", encoding="utf-8")
    repaired = cache.resolve(source, closure)
    assert repaired == hot
    assert ModelArtifactClosureAuthority().freeze(repaired) == closure


def test_runtime_asset_cache_never_duplicates_same_filesystem_source(tmp_path):
    source = _model_root(tmp_path / "source")
    closure = ModelArtifactClosureAuthority().freeze(source)
    cache = ModelRuntimeAssetCache(tmp_path / "cache")
    assert cache.resolve(source, closure) == source


def test_runtime_asset_cache_capacity_pressure_falls_back_to_authoritative_source(
    tmp_path,
    monkeypatch,
):
    source = _model_root(tmp_path / "source")
    closure = ModelArtifactClosureAuthority().freeze(source)
    cache = ModelRuntimeAssetCache(tmp_path / "cache")
    monkeypatch.setattr(
        ModelRuntimeAssetCache,
        "_same_filesystem",
        staticmethod(lambda source, cache_root: False),
    )
    DiskUsage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        cache_module.shutil,
        "disk_usage",
        lambda path: DiskUsage(1024, 1024, 0),
    )
    assert cache.resolve(source, closure) == source
