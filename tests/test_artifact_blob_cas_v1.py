from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Lock

import pytest

import noetrium_platform.evidence.artifact.content.providers.blob_store as blob_module
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobLifecycleState,
    ArtifactBlobStoreError,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
)


def test_concurrent_same_digest_publication_writes_physical_blob_once(
    tmp_path,
    monkeypatch,
) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = (b"research-artifact-" * 8192) + b"tail"
    original = blob_module.durable_publish_immutable_bytes_many
    calls = 0
    guard = Lock()

    def counted(items, *, staging_dir=None):
        nonlocal calls
        with guard:
            calls += 1
        return original(items, staging_dir=staging_dir)

    monkeypatch.setattr(
        blob_module,
        "durable_publish_immutable_bytes_many",
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

    def external_wins(items, *, staging_dir=None):
        del staging_dir
        target, _value = items[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        raise FileExistsError("external immutable publisher won")

    monkeypatch.setattr(
        blob_module,
        "durable_publish_immutable_bytes_many",
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

    def external_corrupt(items, *, staging_dir=None):
        del staging_dir
        target, _value = items[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(foreign)
        raise FileExistsError("external corrupt publisher won")

    monkeypatch.setattr(
        blob_module,
        "durable_publish_immutable_bytes_many",
        external_corrupt,
    )

    with pytest.raises(
        ArtifactBlobStoreError,
        match="failed integrity verification",
    ):
        store.put(payload, media_type="application/octet-stream")

    assert path.read_bytes() == foreign




def _closed_blob_gc(
    store: DirectoryArtifactBlobStore,
    ref,
    *,
    proof_character: str = "a",
    retained_evidence_refs: tuple[str, ...] = (),
):
    closures = (
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.EVIDENCE,
            proof_character * 64,
            retained_evidence_refs,
        ),
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.EXECUTION,
            proof_character * 64,
            (),
        ),
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.RECOVERY,
            proof_character * 64,
            (),
        ),
    )
    return store.assess_gc(ref, closures=closures)


def test_blob_gc_requires_complete_typed_closure(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"closure-required-artifact"
    ref = store.put(payload, media_type="application/octet-stream")
    incomplete = store.assess_gc(
        ref,
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EVIDENCE,
                "1" * 64,
                (),
            ),
        ),
    )

    assert not incomplete.eligible
    with pytest.raises(RuntimeError, match="complete execution, evidence"):
        store.purge(ref, gc=incomplete)
    assert store.get(ref) == payload


def test_blob_gc_rejects_retained_reference(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"retained-reference-artifact"
    ref = store.put(payload, media_type="application/octet-stream")
    blocked = _closed_blob_gc(
        store,
        ref,
        proof_character="2",
        retained_evidence_refs=("evidence:still-retained",),
    )

    assert not blocked.eligible
    with pytest.raises(RuntimeError, match="zero retained references"):
        store.purge(ref, gc=blocked)
    assert store.get(ref) == payload


def test_blob_gc_generation_fences_republished_same_digest(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"generation-fenced-artifact"
    ref = store.put(payload, media_type="application/octet-stream")
    first = store.generation(ref)
    assert first.generation == 1
    assert first.state is ArtifactBlobLifecycleState.ACTIVE

    first_gc = _closed_blob_gc(store, ref, proof_character="a")
    assert first_gc.generation == first.generation
    purged = store.purge(ref, gc=first_gc)
    assert purged.state is ArtifactBlobLifecycleState.PURGED
    assert not store._path(ref.content_sha256).exists()

    republished = store.put(
        payload,
        media_type="application/octet-stream",
    )
    assert republished == ref
    second = store.generation(republished)
    assert second.generation == 2
    assert second.state is ArtifactBlobLifecycleState.ACTIVE

    with pytest.raises(
        ArtifactBlobStoreError,
        match="stale artifact blob generation",
    ):
        store.purge(ref, gc=first_gc)
    assert store.get(republished) == payload


def test_blob_gc_retry_recovers_retiring_generation(
    tmp_path,
    monkeypatch,
) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"retiring-artifact"
    ref = store.put(payload, media_type="application/octet-stream")
    gc = _closed_blob_gc(store, ref, proof_character="b")

    real_unlink = blob_module.durable_unlink
    failed = False

    def fail_once(path):
        nonlocal failed
        if path == store._path(ref.content_sha256) and not failed:
            failed = True
            raise OSError("simulated delete crash")
        return real_unlink(path)

    monkeypatch.setattr(blob_module, "durable_unlink", fail_once)
    with pytest.raises(OSError, match="delete crash"):
        store.purge(ref, gc=gc)

    retiring = store.generation(ref)
    assert retiring.state is ArtifactBlobLifecycleState.RETIRING
    with pytest.raises(
        ArtifactBlobStoreError,
        match="retirement requires recovery",
    ):
        store.put(payload, media_type="application/octet-stream")

    monkeypatch.setattr(blob_module, "durable_unlink", real_unlink)
    purged = store.purge(ref, gc=gc)
    assert purged.state is ArtifactBlobLifecycleState.PURGED
    assert not store._path(ref.content_sha256).exists()


def test_blob_gc_retry_rejects_changed_proof(tmp_path, monkeypatch) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"proof-fenced-artifact"
    ref = store.put(payload, media_type="application/octet-stream")
    original_gc = _closed_blob_gc(store, ref, proof_character="c")

    real_unlink = blob_module.durable_unlink

    def fail_delete(path):
        if path == store._path(ref.content_sha256):
            raise OSError("simulated delete crash")
        return real_unlink(path)

    monkeypatch.setattr(blob_module, "durable_unlink", fail_delete)
    with pytest.raises(OSError, match="delete crash"):
        store.purge(ref, gc=original_gc)

    changed_gc = _closed_blob_gc(store, ref, proof_character="d")
    monkeypatch.setattr(blob_module, "durable_unlink", real_unlink)
    with pytest.raises(
        ArtifactBlobStoreError,
        match="GC proof changed",
    ):
        store.purge(ref, gc=changed_gc)
    assert store.purge(
        ref,
        gc=original_gc,
    ).state is ArtifactBlobLifecycleState.PURGED


def test_purged_blob_split_truth_fails_closed(tmp_path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path / "blobs")
    payload = b"purged-residue"
    ref = store.put(payload, media_type="application/octet-stream")
    gc = _closed_blob_gc(store, ref, proof_character="e")
    store.purge(ref, gc=gc)
    path = store._path(ref.content_sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

    with pytest.raises(
        ArtifactBlobStoreError,
        match="unexpected physical residue",
    ):
        store.generation(ref)
    with pytest.raises(
        ArtifactBlobStoreError,
        match="unexpected physical residue",
    ):
        store.put(payload, media_type="application/octet-stream")
