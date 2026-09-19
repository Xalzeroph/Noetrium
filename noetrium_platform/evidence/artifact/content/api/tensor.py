from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    canonical_digest,
    require_sha256,
)

from .blob import ArtifactBlobRef


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class TensorContentRef:
    """Immutable tensor identity over Artifact content authority.

    The platform stores only tensor metadata plus the content-addressed blob
    identity. Framework objects, device buffers, DLPack capsules and codec
    implementations stay behind TensorContentStorePort.
    """

    content: ArtifactBlobRef
    shape: tuple[int, ...]
    dtype: str
    codec: str
    schema_id: str
    layout: str = "contiguous"
    tensor_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.content, ArtifactBlobRef):
            raise TypeError("tensor content requires ArtifactBlobRef")
        if type(self.shape) is not tuple or not self.shape or any(
            type(value) is not int or value < 0
            for value in self.shape
        ):
            raise ValueError(
                "tensor content shape must be a non-empty tuple of "
                "non-negative integers"
            )
        for field_name in ("dtype", "codec", "schema_id", "layout"):
            object.__setattr__(
                self,
                field_name,
                _text(
                    getattr(self, field_name),
                    f"tensor content {field_name}",
                ),
            )
        object.__setattr__(
            self,
            "tensor_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        value: JsonObject = {
            "content": {
                "content_sha256": self.content.content_sha256,
                "size_bytes": self.content.size_bytes,
                "media_type": self.content.media_type,
            },
            "shape": self.shape,
            "dtype": self.dtype,
            "codec": self.codec,
            "schema_id": self.schema_id,
            "layout": self.layout,
        }
        if include_digest:
            value["tensor_digest"] = self.tensor_digest
        return value

    @classmethod
    def from_payload(cls, value: object) -> "TensorContentRef":
        if not isinstance(value, dict):
            raise TypeError("tensor content payload must be an object")
        content = value.get("content")
        if not isinstance(content, dict):
            raise TypeError("tensor content blob payload must be an object")
        shape = value.get("shape")
        if not isinstance(shape, (tuple, list)):
            raise TypeError("tensor content shape payload must be a sequence")
        ref = cls(
            content=ArtifactBlobRef(
                content_sha256=_text(
                    content.get("content_sha256"),
                    "tensor blob content_sha256",
                ),
                size_bytes=content.get("size_bytes"),
                media_type=_text(
                    content.get("media_type"),
                    "tensor blob media_type",
                ),
            ),
            shape=tuple(shape),
            dtype=value.get("dtype"),
            codec=value.get("codec"),
            schema_id=value.get("schema_id"),
            layout=value.get("layout", "contiguous"),
        )
        supplied = value.get("tensor_digest")
        if supplied is not None and require_sha256(
            supplied,
            "tensor content tensor_digest",
        ) != ref.tensor_digest:
            raise ValueError("tensor content digest mismatch")
        return ref


@runtime_checkable
class TensorContentStorePort(Protocol):
    """Provider-owned tensor serialization/materialization seam."""

    @property
    def identity_digest(self) -> str: ...

    def put(
        self,
        value: object,
        *,
        schema_id: str,
    ) -> TensorContentRef: ...

    def get(self, ref: TensorContentRef) -> object: ...

    def verify(self, ref: TensorContentRef) -> bool: ...


__all__ = [
    "TensorContentRef",
    "TensorContentStorePort",
]
