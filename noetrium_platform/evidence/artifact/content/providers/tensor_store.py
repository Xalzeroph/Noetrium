from __future__ import annotations

from collections.abc import Sequence

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobStorePort,
    TensorContentRef,
    TensorContentStorePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    canonical_digest,
    require_sha256,
    strict_json_loads,
)


_MEDIA_TYPE = "application/vnd.noetrium.tensor+json"
_CODEC = "canonical-json"


def _leaf_dtype(value: object) -> str:
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int64"
    if type(value) is float:
        return "float64"
    raise TypeError(
        "canonical JSON tensor leaves must be bool, int, or float"
    )


def _shape_and_dtype(value: object) -> tuple[tuple[int, ...], str]:
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError("canonical JSON tensor cannot contain text leaves")
    if isinstance(value, Sequence):
        rows = tuple(value)
        if not rows:
            raise ValueError(
                "canonical JSON tensor dimensions must be non-empty"
            )
        child_shape, dtype = _shape_and_dtype(rows[0])
        for item in rows[1:]:
            item_shape, item_dtype = _shape_and_dtype(item)
            if item_shape != child_shape:
                raise ValueError(
                    "canonical JSON tensor must be rectangular"
                )
            if item_dtype == dtype:
                continue
            numeric = {dtype, item_dtype}
            if numeric <= {"int64", "float64"}:
                dtype = "float64"
            else:
                raise TypeError(
                    "canonical JSON tensor leaf dtypes must be homogeneous"
                )
        return (len(rows), *child_shape), dtype
    return (), _leaf_dtype(value)


def _validate_ref_payload(
    value: object,
    ref: TensorContentRef,
) -> None:
    shape, dtype = _shape_and_dtype(value)
    if shape != ref.shape:
        raise ValueError("tensor content shape does not match reference")
    if dtype != ref.dtype:
        raise ValueError("tensor content dtype does not match reference")


class CanonicalJsonTensorContentStore(TensorContentStorePort):
    """Framework-neutral tensor store over Artifact Blob authority.

    This provider intentionally optimizes for reproducibility and portability,
    not throughput. Framework/device-specific tensor codecs can implement the
    same TensorContentStorePort without changing Machine or method semantics.
    """

    def __init__(
        self,
        blob_store: ArtifactBlobStorePort,
        *,
        blob_store_identity_digest: str,
        provider_revision: int = 1,
    ) -> None:
        if not isinstance(blob_store, ArtifactBlobStorePort):
            raise TypeError(
                "canonical tensor store requires ArtifactBlobStorePort"
            )
        self._blob_store = blob_store
        self._blob_store_identity_digest = require_sha256(
            blob_store_identity_digest,
            "tensor blob store identity_digest",
        )
        if type(provider_revision) is not int or provider_revision < 1:
            raise ValueError(
                "tensor provider_revision must be a positive integer"
            )
        self._provider_revision = provider_revision
        self._identity_digest = canonical_digest({
            "provider": "canonical-json-tensor-content-store",
            "provider_revision": provider_revision,
            "codec": _CODEC,
            "media_type": _MEDIA_TYPE,
            "blob_store_identity_digest": (
                self._blob_store_identity_digest
            ),
            "blob_store_durability": getattr(
                blob_store,
                "durability",
                "unspecified",
            ),
        })

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def put(
        self,
        value: object,
        *,
        schema_id: str,
    ) -> TensorContentRef:
        if type(schema_id) is not str or not schema_id.strip():
            raise ValueError("tensor schema_id must be non-empty")
        shape, dtype = _shape_and_dtype(value)
        if not shape:
            raise ValueError(
                "TensorContentRef requires at least one tensor dimension"
            )
        raw = canonical_bytes(value)
        content = self._blob_store.put(
            raw,
            media_type=_MEDIA_TYPE,
        )
        return TensorContentRef(
            content=content,
            shape=shape,
            dtype=dtype,
            codec=_CODEC,
            schema_id=schema_id.strip(),
            layout="contiguous",
        )

    def get(self, ref: TensorContentRef) -> object:
        if not isinstance(ref, TensorContentRef):
            raise TypeError("tensor get requires TensorContentRef")
        if ref.codec != _CODEC:
            raise ValueError(
                f"unsupported tensor codec for this provider: {ref.codec}"
            )
        if ref.content.media_type != _MEDIA_TYPE:
            raise ValueError("tensor media type does not match provider")
        raw = self._blob_store.get(ref.content)
        value = strict_json_loads(raw)
        _validate_ref_payload(value, ref)
        return value

    def verify(self, ref: TensorContentRef) -> bool:
        if not isinstance(ref, TensorContentRef):
            return False
        if ref.codec != _CODEC or ref.content.media_type != _MEDIA_TYPE:
            return False
        if not self._blob_store.verify(ref.content):
            return False
        try:
            self.get(ref)
        except (TypeError, ValueError, RuntimeError):
            return False
        return True


__all__ = ["CanonicalJsonTensorContentStore"]
