from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.substrate.api import ArtifactBlobStorePort, MultimodalPart
from noetrium_platform.foundation.kernel.kernel import JsonInput, canonical_digest, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from .unit_semantics import (
    MULTIMODAL_METHOD_TRAIT,
    multimodal_method_digest,
    multimodal_method_id,
    multimodal_method_input_modalities,
    multimodal_method_input_schema,
    multimodal_method_output_modalities,
    multimodal_method_output_schema,
    multimodal_method_parameters,
    multimodal_method_revision,
    multimodal_method_unit,
    require_multimodal_method,
)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value
from .unit_semantics import (
    MULTIMODAL_METHOD_TRAIT,
    multimodal_method_digest,
    multimodal_method_id,
    multimodal_method_input_modalities,
    multimodal_method_input_schema,
    multimodal_method_output_modalities,
    multimodal_method_output_schema,
    multimodal_method_parameters,
    multimodal_method_revision,
    multimodal_method_unit,
    require_multimodal_method,
)



def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class MultimodalRequest:
    """Dynamic provider-neutral request referencing immutable method semantics."""

    parts: tuple[MultimodalPart, ...]
    instruction: str | None = None
    method: NoetriumUnit | None = None
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)
    schema_id: str = field(init=False, default="model.multimodal.request.v2")

    def __post_init__(self) -> None:
        if type(self.parts) is not tuple or not self.parts:
            raise TypeError("multimodal request parts must be non-empty")
        if any(not isinstance(part, MultimodalPart) for part in self.parts):
            raise TypeError("multimodal request parts must be typed")
        if self.instruction is not None:
            _text(self.instruction, "multimodal request instruction")
        if self.method is not None:
            require_multimodal_method(self.method)
        if not isinstance(self.metadata, Mapping):
            raise TypeError("multimodal request metadata must be mapping")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def digest(self) -> str:
        return canonical_digest(
            {
                "schema_id": self.schema_id,
                "parts": self.parts,
                "instruction": self.instruction,
                "method_digest": None if self.method is None else self.method.unit_digest,
                "metadata": dict(self.metadata),
            }
        )


@dataclass(frozen=True, slots=True)
class MultimodalResponse:
    model_revision: str
    text: str | None = None
    parts: tuple[MultimodalPart, ...] = ()
    method: NoetriumUnit | None = None
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)
    schema_id: str = field(init=False, default="model.multimodal.response.v2")

    def __post_init__(self) -> None:
        _text(self.model_revision, "multimodal response model_revision")
        if self.text is not None:
            _text(self.text, "multimodal response text")
        if type(self.parts) is not tuple or any(
            not isinstance(part, MultimodalPart) for part in self.parts
        ):
            raise TypeError("multimodal response parts must be typed")
        if self.text is None and not self.parts:
            raise ValueError("multimodal response must contain text or parts")
        if self.method is not None:
            require_multimodal_method(self.method)
        if not isinstance(self.metadata, Mapping):
            raise TypeError("multimodal response metadata must be mapping")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    def digest(self) -> str:
        return canonical_digest(
            {
                "schema_id": self.schema_id,
                "model_revision": self.model_revision,
                "text": self.text,
                "parts": self.parts,
                "method_digest": None if self.method is None else self.method.unit_digest,
                "metadata": dict(self.metadata),
            }
        )


@runtime_checkable
class MultimodalRequestCodecPort(Protocol):
    def encode(
        self,
        request: MultimodalRequest,
        content: ArtifactBlobStorePort,
    ) -> Mapping[str, JsonInput]: ...


__all__ = [
    "MULTIMODAL_METHOD_TRAIT",
    "MultimodalPart",
    "MultimodalRequest",
    "MultimodalRequestCodecPort",
    "MultimodalResponse",
    "multimodal_method_digest",
    "multimodal_method_id",
    "multimodal_method_input_modalities",
    "multimodal_method_input_schema",
    "multimodal_method_output_modalities",
    "multimodal_method_output_schema",
    "multimodal_method_parameters",
    "multimodal_method_revision",
    "multimodal_method_unit",
    "require_multimodal_method",
]
