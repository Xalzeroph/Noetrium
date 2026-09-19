from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model._persisted import exact_fields, optional_text, text, text_tuple
from noetrium_platform.capabilities.model.asset.api import ManagedModelAsset, ModelAssetMode, ModelAssetOrigin
from noetrium_platform.foundation.scope.api import scope_from_data, scope_to_data


_ASSET_FIELDS = frozenset({
    "model_id", "scope", "path", "mode", "family", "notes", "tags", "storage_pool", "origin",
})
_ORIGIN_FIELDS = frozenset({"backend", "source", "revision"})


def encode_model_asset(value: ManagedModelAsset) -> bytes:
    return json.dumps({
        "model_id": value.model_id,
        "scope": scope_to_data(value.scope),
        "path": str(value.path),
        "mode": value.mode.value,
        "family": value.family,
        "notes": value.notes,
        "tags": list(value.tags),
        "storage_pool": value.storage_pool,
        "origin": None if value.origin is None else {
            "backend": value.origin.backend,
            "source": value.origin.source,
            "revision": value.origin.revision,
        },
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_model_asset(data: dict[str, object]) -> ManagedModelAsset:
    document = exact_fields(data, field="model asset", fields=_ASSET_FIELDS)
    origin_value = document["origin"]
    origin = None
    if origin_value is not None:
        origin_data = exact_fields(origin_value, field="model asset origin", fields=_ORIGIN_FIELDS)
        origin = ModelAssetOrigin(
            backend=text(origin_data["backend"], field="origin.backend", allow_empty=False),
            source=text(origin_data["source"], field="origin.source", allow_empty=False),
            revision=optional_text(origin_data["revision"], field="origin.revision"),
        )
    return ManagedModelAsset(
        model_id=text(document["model_id"], field="model_id", allow_empty=False),
        scope=scope_from_data(document["scope"]),
        path=Path(text(document["path"], field="path", allow_empty=False)),
        mode=ModelAssetMode(text(document["mode"], field="mode", allow_empty=False)),
        family=text(document["family"], field="family"),
        notes=text(document["notes"], field="notes"),
        origin=origin,
        tags=text_tuple(document["tags"], field="tags"),
        storage_pool=optional_text(document["storage_pool"], field="storage_pool"),
    )


__all__ = ["decode_model_asset", "encode_model_asset"]
