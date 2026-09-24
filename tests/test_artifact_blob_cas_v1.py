from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
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
    original = blob_module.durable_publish_immutable_bytes
    calls = 0
    guard = Lock()

    def counted(path, value, *, staging_dir=None):
        nonlocal calls
        with guard:
            calls += 1
        return original(path, value, staging_dir=staging_dir)

    monkeypatch.setattr(
        blob_module,
        "durable_publish_immutable_bytes",
        counted,
    )

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
    digests = tuple(
        sha256(f"artifact-{index}".encode()).hexdigest()
        for index in range(600)
    )
    lock_paths = {store._lock_path(digest) for digest in digests}
    local_indices = {store._shard_index(digest) for digest in digests}
    assert len(store._local_locks) == 256
    assert len(lock_paths) <= 256
    assert len(local_indices) <= 256


def test_blob_resolver_reconstructs_verified_ref_without_host_path(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"materialized-benchmark-bytes"
    published = store.put(payload, media_type="application/jsonl")

    resolved = store.resolve(
        published.content_sha256,
        media_type=published.media_type,
    )

    assert resolved == published
    assert store.get(resolved) == payload


def test_blob_resolver_fails_closed_on_missing_or_invalid_digest(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        store.resolve("invalid", media_type="application/octet-stream")
    with pytest.raises(ArtifactBlobStoreError, match="missing"):
        store.resolve("a" * 64, media_type="application/octet-stream")



def test_blob_retry_discards_hard_kill_staging_residue(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"complete-immutable-artifact"
    digest = sha256(payload).hexdigest()
    path = store._path(digest)
    stranded = store._staging_root / (
        f"{path.name}.immutable.999999.simulated-hard-kill"
    )
    stranded.write_bytes(b"partial-noncanonical-residue")

    assert not path.exists()
    assert stranded.exists()

    ref = store.put(payload, media_type="application/octet-stream")

    assert ref.content_sha256 == digest
    assert path.read_bytes() == payload
    assert not stranded.exists()
    assert tuple(store._staging_root.iterdir()) == ()


def test_external_exact_blob_publisher_is_verified_not_overwritten(
    tmp_path,
    monkeypatch,
) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"external-exact-artifact"
    digest = sha256(payload).hexdigest()
    path = store._path(digest)

    def external_wins(target, value, *, staging_dir=None):
        del value, staging_dir
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        raise FileExistsError("external immutable publisher won")

    monkeypatch.setattr(
        blob_module,
        "durable_publish_immutable_bytes",
        external_wins,
    )

    ref = store.put(payload, media_type="application/octet-stream")
    assert ref.content_sha256 == digest
    assert path.read_bytes() == payload


def test_external_corrupt_blob_publisher_fails_closed_without_overwrite(
    tmp_path,
    monkeypatch,
) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"owned-artifact"
    digest = sha256(payload).hexdigest()
    path = store._path(digest)
    foreign = b"foreign-corrupt"

    def external_corrupt(target, value, *, staging_dir=None):
        del value, staging_dir
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(foreign)
        raise FileExistsError("external corrupt publisher won")

    monkeypatch.setattr(
        blob_module,
        "durable_publish_immutable_bytes",
        external_corrupt,
    )

    with pytest.raises(
        ArtifactBlobStoreError,
        match="failed integrity verification",
    ):
        store.put(payload, media_type="application/octet-stream")

    assert path.read_bytes() == foreign
