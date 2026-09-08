from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.model.request.api import ContentAddressedStorePort, ContentRef
from noetrium_platform.foundation.kernel.kernel import JsonInput, canonical_digest, freeze_json


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _tokens(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    values = tuple(_text(value, field_name) for value in values)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class MultimodalMethodSpec:
    """Method-owned schema and parameters; modality identifiers are open strings."""

    method_id: str
    revision: str
    input_schema_id: str
    output_schema_id: str
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    parameters: Mapping[str, JsonInput] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("method_id", "revision", "input_schema_id", "output_schema_id"):
            _text(getattr(self, name), f"multimodal method {name}")
        object.__setattr__(self, "input_modalities", _tokens(self.input_modalities, "input_modalities"))
        object.__setattr__(self, "output_modalities", _tokens(self.output_modalities, "output_modalities"))
        if not isinstance(self.parameters, Mapping):
            raise TypeError("multimodal method parameters must be a mapping")
        object.__setattr__(self, "parameters", freeze_json(self.parameters))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MultimodalPart:
    """Immutable part; bytes live in ContentAddressedStore, never in this object."""

    role: str
    content: ContentRef
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
        if not isinstance(self.content, ContentRef):
            raise TypeError("multimodal part content must be ContentRef")
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


@dataclass(frozen=True, slots=True)
class MultimodalRequest:
    """Provider-neutral request; a method may contain any number of any parts."""

    parts: tuple[MultimodalPart, ...]
    instruction: str | None = None
    method: MultimodalMethodSpec | None = None
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)
    schema_id: str = field(init=False, default="model.multimodal.request.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.parts, tuple) or not self.parts:
            raise TypeError("multimodal request parts must be non-empty")
        if any(not isinstance(part, MultimodalPart) for part in self.parts):
            raise TypeError("multimodal request parts must be typed")
        if self.instruction is not None:
            _text(self.instruction, "multimodal request instruction")
        if self.method is not None and not isinstance(self.method, MultimodalMethodSpec):
            raise TypeError("multimodal request method must be typed")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("multimodal request metadata must be a mapping")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MultimodalResponse:
    model_revision: str
    text: str | None = None
    parts: tuple[MultimodalPart, ...] = ()
    method: MultimodalMethodSpec | None = None
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)
    schema_id: str = field(init=False, default="model.multimodal.response.v1")

    def __post_init__(self) -> None:
        _text(self.model_revision, "multimodal response model_revision")
        if self.text is not None:
            _text(self.text, "multimodal response text")
        if not isinstance(self.parts, tuple) or any(not isinstance(part, MultimodalPart) for part in self.parts):
            raise TypeError("multimodal response parts must be typed")
        if self.text is None and not self.parts:
            raise ValueError("multimodal response must contain text or parts")
        if self.method is not None and not isinstance(self.method, MultimodalMethodSpec):
            raise TypeError("multimodal response method must be typed")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("multimodal response metadata must be a mapping")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def digest(self) -> str:
        return canonical_digest(self)


@runtime_checkable
class MultimodalRequestCodecPort(Protocol):
    """Provider-owned boundary: only codecs know how a method is serialized."""

    def encode(self, request: MultimodalRequest, content: ContentAddressedStorePort) -> Mapping[str, JsonInput]:
        ...


__all__ = [
    "MultimodalMethodSpec",
    "MultimodalPart",
    "MultimodalRequest",
    "MultimodalRequestCodecPort",
    "MultimodalResponse",
]
