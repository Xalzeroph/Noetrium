from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json

from noetrium_platform.capabilities.model.asset.api import ModelSourceSpec


_SCHEMA = "noetrium.model-source-catalog.v1"


@dataclass(frozen=True, slots=True)
class ModelSourceCatalogEntry:
    model_id: str
    source: ModelSourceSpec
    family: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model source catalog model_id is required")
        if not isinstance(self.source, ModelSourceSpec):
            raise TypeError("model source catalog source must be ModelSourceSpec")
        if type(self.family) is not str:
            raise TypeError("model source catalog family must be text")
        if type(self.tags) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.tags
        ):
            raise TypeError("model source catalog tags must be non-empty strings")


class PackagedModelSourceCatalog:
    """Read-only platform source policy for logical model identities."""

    def __init__(self) -> None:
        resource = files(__package__).joinpath("default_sources.json")
        document = json.loads(resource.read_text("utf-8"))
        if document.get("schema") != _SCHEMA:
            raise RuntimeError("packaged model source catalog schema drift")
        rows = document.get("models")
        if not isinstance(rows, dict):
            raise RuntimeError("packaged model source catalog models must be object")
        entries: dict[str, ModelSourceCatalogEntry] = {}
        for model_id, row in rows.items():
            if type(model_id) is not str or not model_id.strip() or not isinstance(row, dict):
                raise RuntimeError("packaged model source catalog row is invalid")
            source = ModelSourceSpec(
                backend=str(row["backend"]),
                source=str(row["source"]),
                revision=(
                    None
                    if row.get("revision") is None
                    else str(row["revision"])
                ),
                storage_pool=str(row.get("storage_pool", "default")),
                include=tuple(str(v) for v in row.get("include", ())),
                exclude=tuple(str(v) for v in row.get("exclude", ())),
                resume=bool(row.get("resume", True)),
                max_workers=(
                    None
                    if row.get("max_workers") is None
                    else int(row["max_workers"])
                ),
            )
            entries[model_id] = ModelSourceCatalogEntry(
                model_id=model_id,
                source=source,
                family=str(row.get("family", "")),
                tags=tuple(str(v) for v in row.get("tags", ())),
            )
        self._entries = entries

    def resolve(self, model_id: str) -> ModelSourceCatalogEntry:
        if type(model_id) is not str or not model_id.strip():
            raise ValueError("model source lookup requires model_id")
        try:
            return self._entries[model_id]
        except KeyError as exc:
            raise KeyError(
                "no platform model source is registered for logical model: "
                + model_id
            ) from exc

    def entries(self) -> tuple[ModelSourceCatalogEntry, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))


__all__ = [
    "ModelSourceCatalogEntry",
    "PackagedModelSourceCatalog",
]
