from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.evidence.artifact.content.api import TensorContentRef
from noetrium_platform.evidence.artifact.content.providers import (
    CanonicalJsonTensorContentStore,
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _store(root: Path) -> CanonicalJsonTensorContentStore:
    blob = DirectoryArtifactBlobStore(root / "blob")
    return CanonicalJsonTensorContentStore(
        blob,
        blob_store_identity_digest=canonical_digest({
            "provider": "directory-artifact-blob-store",
            "root": str((root / "blob").resolve()),
        }),
    )


def test_tensor_content_store_roundtrips_rectangular_numeric_tensor(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    value = (
        ((1.0, 2.0), (3.0, 4.0)),
        ((5.0, 6.0), (7.0, 8.0)),
    )

    ref = store.put(value, schema_id="test.tensor.v1")

    assert ref.shape == (2, 2, 2)
    assert ref.dtype == "float64"
    assert ref.codec == "canonical-json"
    assert store.verify(ref) is True
    assert store.get(ref) == [
        [[1.0, 2.0], [3.0, 4.0]],
        [[5.0, 6.0], [7.0, 8.0]],
    ]


def test_tensor_content_schema_changes_identity_not_blob_content(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    value = ((1, 2), (3, 4))

    first = store.put(value, schema_id="paper.embedding.v1")
    second = store.put(value, schema_id="paper.weights.v1")

    assert first.content == second.content
    assert first.tensor_digest != second.tensor_digest
    assert first.dtype == "int64"
    assert second.dtype == "int64"


def test_tensor_content_verify_rejects_metadata_shape_drift(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    ref = store.put(((1.0, 2.0),), schema_id="test.tensor.v1")
    drifted = TensorContentRef(
        content=ref.content,
        shape=(2, 1),
        dtype=ref.dtype,
        codec=ref.codec,
        schema_id=ref.schema_id,
        layout=ref.layout,
    )

    assert store.verify(drifted) is False


def test_tensor_content_store_rejects_ragged_or_text_tensors(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="rectangular"):
        store.put(((1.0, 2.0), (3.0,)), schema_id="test.ragged")

    with pytest.raises(TypeError, match="text"):
        store.put((("token",),), schema_id="test.text")
