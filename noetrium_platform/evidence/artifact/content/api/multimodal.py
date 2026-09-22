from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import JsonInput, freeze_json
from .blob import ArtifactBlobRef


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value

@dataclass(frozen=True, slots=True)
class MultimodalPart:
    """Immutable part; bytes live in ArtifactBlobStore, never in this object."""

    role: str
    content: ArtifactBlobRef
    modality_id: str | None = None
    encoding: str | None = None
    part_id: str | None = None
    sequence_index: int = 0
    timestamp_ns: int | None = None
    duration_ns: int | None = None
    coordinate_frame: str | None = None
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.role, "multimodal part role")
        if not isinstance(self.content, ArtifactBlobRef):
            raise TypeError("multimodal part content must be ArtifactBlobRef")
        object.__setattr__(self, "modality_id", _text(
            self.content.media_type if self.modality_id is None else self.modality_id,
            "multimodal part modality_id",
        ))
        if self.encoding is not None:
            _text(self.encoding, "multimodal part encoding")
        if self.part_id is not None:
            _text(self.part_id, "multimodal part part_id")
        if type(self.sequence_index) is not int or self.sequence_index < 0:
            raise ValueError("multimodal part sequence_index must be non-negative")
        for name in ("timestamp_ns", "duration_ns"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"multimodal part {name} must be non-negative")
        if self.coordinate_frame is not None:
            _text(self.coordinate_frame, "multimodal part coordinate_frame")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("multimodal part metadata must be a mapping")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        if not isinstance(self.source_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.source_refs
        ):
            raise TypeError("multimodal part source_refs must be non-empty strings")


__all__ = ["MultimodalPart"]
