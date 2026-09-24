from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest

import noetrium_platform.evidence.artifact.content.providers.blob_store as blob_module
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobStoreError
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)


def test_concurrent_same_digest_publication_writes_physical_blob_once(
    tmp_path,
    monkeypatch,
) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = (b"research-artifact-" * 8192) + b"tail"
    original = blob_module.atomic_replace_bytes
    calls = 0
    guard = Lock()

    def counted(path, value):
        nonlocal calls
        with guard:
            calls += 1
        return original(path, value)

    monkeypatch.setattr(blob_module, "atomic_replace_bytes", counted)

    def publish(_index: int):
        return store.put(
            payload,
            media_type="application/octet-stream",
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        refs = tuple(executor.map(publish, range(64)))

    assert calls == 1
    assert len({ref.content_sha256 for ref in refs}) == 1
    assert len({ref.size_bytes for ref in refs}) == 1
    assert store.get(refs[0]) == payload


def test_existing_corrupt_digest_path_fails_closed_without_overwrite(
    tmp_path,
) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"authoritative-artifact"
    ref = store.put(payload, media_type="application/octet-stream")
    path = store._path(ref.content_sha256)
    corrupt = b"x" * len(payload)
    assert corrupt != payload
    path.write_bytes(corrupt)

    with pytest.raises(
        ArtifactBlobStoreError,
        match="failed integrity verification",
    ):
        store.put(payload, media_type="application/octet-stream")

    assert path.read_bytes() == corrupt


def test_blob_lock_domain_is_fixed_size_not_per_artifact(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    for index in range(600):
        store.put(
            f"artifact-{index}".encode(),
            media_type="application/octet-stream",
        )
    lock_files = tuple((tmp_path / "blobs" / ".locks").glob("*.lock"))
    assert len(store._local_locks) == 256
    assert len(lock_files) <= 256
