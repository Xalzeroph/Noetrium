from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from threading import Event, Thread
from unittest import mock

import pytest

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind
from noetrium_platform.evidence.artifact.catalog.runtime import InMemoryArtifactRegistry
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactAcquisitionError,
    ArtifactAcquisitionRequest,
    ArtifactAcquisitionResult,
    ArtifactStorageBindingConflict,
    ArtifactStorageBindingCorruptionError,
    ArtifactStorageVerificationError,
)
from noetrium_platform.evidence.artifact.content.composition import compose_artifact_acquisition
from noetrium_platform.evidence.artifact.content.providers import (
    FilesystemArtifactStoragePlacementVerifier,
    SQLiteArtifactStorageBindingStore,
    download as download_provider,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        del size
        payload, self._payload = self._payload, b""
        return payload

    def close(self) -> None:
        self.closed = True


def test_generic_artifact_acquisition_atomically_publishes_and_reuses_verified_file(tmp_path) -> None:
    payload = b"runtime-artifact-bytes"
    sha1 = hashlib.sha1(payload).hexdigest()
    calls: list[str] = []

    def opener(request, timeout):
        del timeout
        calls.append(request.full_url)
        return _Response(payload)

    assembly = compose_artifact_acquisition(opener=opener)
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.test",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "server.jar"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha1=sha1,
    )
    first = assembly.acquirer.acquire(request)
    second = assembly.acquirer.acquire(request)

    assert first.downloaded is True
    assert second.downloaded is False
    assert first.record.digest == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "server.jar").read_bytes() == payload
    assert calls == [request.source_url]

    registry = InMemoryArtifactRegistry()
    assert registry.put(first.record) == first.record


def test_verified_existing_artifact_is_hashed_once_on_reuse(tmp_path) -> None:
    payload = b"large-artifact-simulation"
    assembly = compose_artifact_acquisition(opener=lambda request, timeout: _Response(payload))
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.reuse-hash",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )
    assembly.acquirer.acquire(request)
    with mock.patch.object(download_provider, "_digests", wraps=download_provider._digests) as digests:
        reused = assembly.acquirer.acquire(request)
    assert reused.downloaded is False
    assert digests.call_count == 1


def test_generic_artifact_acquisition_fails_closed_on_digest_mismatch(tmp_path) -> None:
    payload = b"not-the-expected-server"

    def opener(request, timeout):
        del request, timeout
        return _Response(payload)

    assembly = compose_artifact_acquisition(opener=opener)
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.bad",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "server.jar"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha1="0" * 40,
    )
    with pytest.raises(ArtifactAcquisitionError, match="SHA1_MISMATCH"):
        assembly.acquirer.acquire(request)
    assert not (tmp_path / "server.jar").exists()


def test_artifact_acquisition_cleanup_failure_is_typed_and_preserves_primary_failure(tmp_path) -> None:
    payload = b"not-the-expected-artifact"
    assembly = compose_artifact_acquisition(opener=lambda request, timeout: _Response(payload))
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.cleanup-failure",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256="0" * 64,
    )
    with mock.patch.object(Path, "unlink", side_effect=PermissionError("cleanup blocked")):
        with pytest.raises(ArtifactAcquisitionError) as caught:
            assembly.acquirer.acquire(request)

    assert caught.value.code == "TEMP_CLEANUP_FAILED"
    assert isinstance(caught.value.__cause__, ArtifactAcquisitionError)
    assert caught.value.__cause__.code == "SHA256_MISMATCH"
    assert "PermissionError: cleanup blocked" in str(caught.value)


def test_artifact_acquisition_cleanup_failure_preserves_wrapped_download_failure(tmp_path) -> None:
    def opener(request, timeout):
        del request, timeout
        raise OSError("network failed")

    assembly = compose_artifact_acquisition(opener=opener)
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.cleanup-download-failure",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256="0" * 64,
    )
    with mock.patch.object(Path, "unlink", side_effect=PermissionError("cleanup blocked")):
        with pytest.raises(ArtifactAcquisitionError) as caught:
            assembly.acquirer.acquire(request)

    assert caught.value.code == "TEMP_CLEANUP_FAILED"
    assert isinstance(caught.value.__cause__, ArtifactAcquisitionError)
    assert caught.value.__cause__.code == "DOWNLOAD_FAILED"
    assert "OSError: network failed" in str(caught.value.__cause__)


def test_artifact_acquisition_cleanup_failure_does_not_mask_base_exception(tmp_path) -> None:
    class AbortAcquisition(BaseException):
        pass

    def opener(request, timeout):
        del request, timeout
        raise AbortAcquisition("stop now")

    assembly = compose_artifact_acquisition(opener=opener)
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.cleanup-abort",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256="0" * 64,
    )
    with mock.patch.object(Path, "unlink", side_effect=PermissionError("cleanup blocked")):
        with pytest.raises(AbortAcquisition) as caught:
            assembly.acquirer.acquire(request)

    assert caught.value.__notes__
    assert "PermissionError: cleanup blocked" in caught.value.__notes__[0]



def test_response_close_failure_does_not_mask_http_status(tmp_path) -> None:
    class CloseFailingResponse(_Response):
        status = 503

        def close(self) -> None:
            raise PermissionError("response close blocked")

    assembly = compose_artifact_acquisition(
        opener=lambda request, timeout: CloseFailingResponse(b"service unavailable")
    )
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.http-close-failure",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256="0" * 64,
    )
    with pytest.raises(ArtifactAcquisitionError) as caught:
        assembly.acquirer.acquire(request)

    assert caught.value.code == "HTTP_STATUS"
    assert caught.value.__notes__
    assert "response close failed" in caught.value.__notes__[0]
    assert "PermissionError" in caught.value.__notes__[0]
    assert not (tmp_path / "runtime.bin").exists()


def test_response_close_failure_preserves_read_failure(tmp_path) -> None:
    class ReadAndCloseFailingResponse(_Response):
        def read(self, size: int = -1) -> bytes:
            del size
            raise OSError("body read failed")

        def close(self) -> None:
            raise PermissionError("response close blocked")

    assembly = compose_artifact_acquisition(
        opener=lambda request, timeout: ReadAndCloseFailingResponse(b"")
    )
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.read-close-failure",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256="0" * 64,
    )
    with pytest.raises(ArtifactAcquisitionError) as caught:
        assembly.acquirer.acquire(request)
    assert caught.value.code == "DOWNLOAD_FAILED"
    assert "OSError: body read failed" in str(caught.value)
    assert isinstance(caught.value.__cause__, OSError)
    assert any("response close failed" in note for note in caught.value.__cause__.__notes__)


def test_response_close_failure_does_not_mask_base_exception(tmp_path) -> None:
    class AbortRead(BaseException):
        pass

    class AbortAndCloseFailingResponse(_Response):
        def read(self, size: int = -1) -> bytes:
            del size
            raise AbortRead("abort body read")

        def close(self) -> None:
            raise PermissionError("response close blocked")

    assembly = compose_artifact_acquisition(
        opener=lambda request, timeout: AbortAndCloseFailingResponse(b"")
    )
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.abort-close-failure",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "runtime.bin"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256="0" * 64,
    )
    with pytest.raises(AbortRead) as caught:
        assembly.acquirer.acquire(request)
    assert any("response close failed" in note for note in caught.value.__notes__)

def test_concurrent_artifact_publication_has_one_destination_owner(tmp_path) -> None:
    payload = b"one-immutable-runtime-artifact"
    sha256 = hashlib.sha256(payload).hexdigest()
    first_opened = Event()
    release_first = Event()
    first_results = []
    first_errors = []

    def opener(request, timeout):
        del request, timeout
        if not first_opened.is_set():
            first_opened.set()
            assert release_first.wait(5)
        return _Response(payload)

    assembly = compose_artifact_acquisition(opener=opener)
    request = ArtifactAcquisitionRequest(
        artifact_id="runtime.artifact.concurrent",
        source_url="https://artifacts.example.invalid/runtime.bin",
        destination=str(tmp_path / "server.jar"),
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.RUNTIME,
        producer_component_id="test",
        expected_sha256=sha256,
    )

    def first_acquire() -> None:
        try:
            first_results.append(assembly.acquirer.acquire(request))
        except BaseException as exc:
            first_errors.append(exc)

    thread = Thread(target=first_acquire)
    thread.start()
    assert first_opened.wait(5)
    try:
        with pytest.raises(ArtifactAcquisitionError) as caught:
            assembly.acquirer.acquire(request)
        assert caught.value.code == "PUBLICATION_BUSY"
    finally:
        release_first.set()
        thread.join(5)

    assert not thread.is_alive()
    assert first_errors == []
    assert len(first_results) == 1
    assert first_results[0].downloaded is True
    assert (tmp_path / "server.jar").read_bytes() == payload


def test_artifact_storage_relocation_preserves_logical_identity_and_requires_cas(tmp_path) -> None:
    payload = b"portable-artifact-content"
    digest = hashlib.sha256(payload).hexdigest()
    assembly = compose_artifact_acquisition(
        opener=lambda request, timeout: _Response(payload)
    )
    common = dict(
        artifact_id="scientific.portable.result",
        source_url="https://artifacts.example.invalid/portable.bin",
        scope=PLATFORM_SCOPE,
        kind=ArtifactKind.SCIENTIFIC,
        producer_component_id="test.portable",
        expected_sha256=digest,
    )
    first = assembly.acquirer.acquire(
        ArtifactAcquisitionRequest(destination=str(tmp_path / "root-a" / "result.bin"), **common)
    )
    second = assembly.acquirer.acquire(
        ArtifactAcquisitionRequest(destination=str(tmp_path / "root-b" / "result.bin"), **common)
    )

    assert first.record == second.record
    assert not hasattr(first.record, "location")
    assert first.location != second.location
    assert Path(first.location).read_bytes() == Path(second.location).read_bytes() == payload

    verifier = FilesystemArtifactStoragePlacementVerifier()
    placement_path = tmp_path / "artifact-placement.sqlite3"
    store = SQLiteArtifactStorageBindingStore(
        placement_path, placement_verifier=verifier
    )
    initial = store.bind(
        artifact_id=first.record.artifact_id,
        content_sha256=first.record.digest,
        storage_provider_id=first.storage_provider_id,
        location=first.location,
    )
    moved = store.relocate(
        first.record.artifact_id,
        expected_generation=initial.generation,
        storage_provider_id=second.storage_provider_id,
        location=second.location,
    )
    assert moved.generation == 2
    assert moved.content_sha256 == first.record.digest
    assert store.resolve(first.record.artifact_id) == moved
    reopened = SQLiteArtifactStorageBindingStore(
        placement_path, placement_verifier=verifier
    )
    assert reopened.resolve(first.record.artifact_id) == moved

    with pytest.raises(ArtifactStorageVerificationError) as missing:
        store.relocate(
            first.record.artifact_id,
            expected_generation=2,
            storage_provider_id="artifact.filesystem",
            location=str(tmp_path / "missing.bin"),
        )
    assert missing.value.code == "PLACEMENT_NOT_FOUND"
    assert store.resolve(first.record.artifact_id) == moved

    wrong = tmp_path / "wrong.bin"
    wrong.write_bytes(b"wrong-content")
    with pytest.raises(ArtifactStorageVerificationError) as mismatch:
        store.relocate(
            first.record.artifact_id,
            expected_generation=2,
            storage_provider_id="artifact.filesystem",
            location=str(wrong),
        )
    assert mismatch.value.code == "CONTENT_SHA256_MISMATCH"
    assert store.resolve(first.record.artifact_id) == moved

    with pytest.raises(ArtifactStorageBindingConflict):
        store.relocate(
            first.record.artifact_id,
            expected_generation=1,
            storage_provider_id="artifact.filesystem",
            location=str(tmp_path / "stale.bin"),
        )
    with pytest.raises(ArtifactStorageVerificationError):
        store.bind(
            artifact_id=first.record.artifact_id,
            content_sha256="0" * 64,
            storage_provider_id="artifact.filesystem",
            location=first.location,
        )



class _ArmedFilesystemRaceVerifier:
    def __init__(self) -> None:
        self._delegate = FilesystemArtifactStoragePlacementVerifier()
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    def verify(self, **kwargs):
        result = self._delegate.verify(**kwargs)
        if self._armed:
            self._armed = False
            Path(result.location).write_bytes(b"raced-after-verification")
        return result


def test_artifact_storage_resolve_reverifies_post_bind_and_reopen_bytes(tmp_path) -> None:
    content = tmp_path / "managed.bin"
    payload = b"verified-snapshot"
    content.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path = tmp_path / "bindings.sqlite3"
    verifier = FilesystemArtifactStoragePlacementVerifier()
    store = SQLiteArtifactStorageBindingStore(path, placement_verifier=verifier)
    binding = store.bind(
        artifact_id="artifact:snapshot",
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=str(content),
    )
    content.write_bytes(b"tampered-after-bind")
    with pytest.raises(ArtifactStorageVerificationError) as tampered:
        store.resolve(binding.artifact_id)
    assert tampered.value.code == "CONTENT_SHA256_MISMATCH"
    reopened = SQLiteArtifactStorageBindingStore(path, placement_verifier=verifier)
    with pytest.raises(ArtifactStorageVerificationError):
        reopened.resolve(binding.artifact_id)
    content.write_bytes(payload)
    assert reopened.resolve(binding.artifact_id) == binding



def test_artifact_storage_bind_verify_to_cas_race_rolls_back(tmp_path) -> None:
    payload = b"race-safe-content"
    content = tmp_path / "race.bin"
    content.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path = tmp_path / "race-bindings.sqlite3"
    verifier = _ArmedFilesystemRaceVerifier()
    verifier.arm()
    store = SQLiteArtifactStorageBindingStore(path, placement_verifier=verifier)
    with pytest.raises(ArtifactStorageVerificationError) as raced:
        store.bind(
            artifact_id="artifact:race",
            content_sha256=digest,
            storage_provider_id="artifact.filesystem",
            location=str(content),
        )
    assert raced.value.code == "CONTENT_SHA256_MISMATCH"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM artifact_storage_bindings").fetchone()[0] == 0


def test_artifact_storage_relocation_recovers_from_bad_source_and_reverifies_destination(tmp_path) -> None:
    payload = b"relocation-recovery"
    digest = hashlib.sha256(payload).hexdigest()
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(payload)
    destination.write_bytes(payload)
    verifier = FilesystemArtifactStoragePlacementVerifier()
    store = SQLiteArtifactStorageBindingStore(
        tmp_path / "relocate.sqlite3", placement_verifier=verifier
    )
    initial = store.bind(
        artifact_id="artifact:recover",
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=str(source),
    )
    source.write_bytes(b"broken-source")
    with pytest.raises(ArtifactStorageVerificationError):
        store.resolve(initial.artifact_id)
    moved = store.relocate(
        initial.artifact_id,
        expected_generation=1,
        storage_provider_id="artifact.filesystem",
        location=str(destination),
    )
    assert moved.generation == 2
    destination.write_bytes(b"broken-destination")
    with pytest.raises(ArtifactStorageVerificationError):
        store.resolve(initial.artifact_id)



def test_artifact_storage_relocation_verify_to_cas_race_preserves_generation(tmp_path) -> None:
    payload = b"relocation-race-safe"
    digest = hashlib.sha256(payload).hexdigest()
    source = tmp_path / "race-source.bin"
    destination = tmp_path / "race-destination.bin"
    source.write_bytes(payload)
    destination.write_bytes(payload)
    verifier = _ArmedFilesystemRaceVerifier()
    store = SQLiteArtifactStorageBindingStore(
        tmp_path / "race-relocate.sqlite3", placement_verifier=verifier
    )
    initial = store.bind(
        artifact_id="artifact:relocate-race",
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=str(source),
    )
    verifier.arm()
    with pytest.raises(ArtifactStorageVerificationError) as raced:
        store.relocate(
            initial.artifact_id,
            expected_generation=1,
            storage_provider_id="artifact.filesystem",
            location=str(destination),
        )
    assert raced.value.code == "CONTENT_SHA256_MISMATCH"
    assert store.resolve(initial.artifact_id) == initial

def test_artifact_storage_binding_detects_tamper_and_reader_is_read_only(tmp_path) -> None:
    path = tmp_path / "artifact-placement.sqlite3"
    content = tmp_path / "root-a" / "result.bin"
    content.parent.mkdir(parents=True)
    content.write_bytes(b"tamper-test-content")
    digest = hashlib.sha256(content.read_bytes()).hexdigest()
    store = SQLiteArtifactStorageBindingStore(
        path, placement_verifier=FilesystemArtifactStoragePlacementVerifier()
    )
    binding = store.bind(
        artifact_id="artifact:tamper",
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=str(content),
    )
    with store._connect_reader() as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM artifact_storage_bindings")
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE artifact_storage_bindings SET location=? WHERE artifact_id=?",
            (str(tmp_path / "tampered.bin"), binding.artifact_id),
        )
        db.commit()
    with pytest.raises(ArtifactStorageBindingCorruptionError):
        store.resolve(binding.artifact_id)


def test_artifact_storage_binding_rejects_unknown_schema_shape(tmp_path) -> None:
    path = tmp_path / "legacy-placement.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE artifact_storage_bindings("
            "artifact_id TEXT PRIMARY KEY,content_sha256 TEXT NOT NULL,"
            "storage_provider_id TEXT NOT NULL,location TEXT NOT NULL,"
            "generation INTEGER NOT NULL,record_sha256 TEXT NOT NULL,"
            "legacy_path TEXT)"
        )
        db.commit()
    with pytest.raises(ArtifactStorageBindingCorruptionError, match="unsupported artifact storage schema"):
        SQLiteArtifactStorageBindingStore(
            path,
            placement_verifier=FilesystemArtifactStoragePlacementVerifier(),
        )


def test_artifact_acquisition_result_rejects_incoherent_verified_receipt(tmp_path) -> None:
    payload = b"verified-result-contract"
    assembly = compose_artifact_acquisition(
        opener=lambda request, timeout: _Response(payload)
    )
    result = assembly.acquirer.acquire(
        ArtifactAcquisitionRequest(
            artifact_id="artifact:result-contract",
            source_url="https://artifacts.example.invalid/result.bin",
            destination=str(tmp_path / "result.bin"),
            scope=PLATFORM_SCOPE,
            kind=ArtifactKind.RUNTIME,
            producer_component_id="test.result-contract",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    values = dict(
        record=result.record,
        storage_provider_id=result.storage_provider_id,
        location=result.location,
        downloaded=result.downloaded,
        sha256=result.sha256,
        sha1=result.sha1,
        size=result.size,
    )
    with pytest.raises(ValueError, match="record digest must match"):
        ArtifactAcquisitionResult(**(values | {"sha256": "0" * 64}))
    with pytest.raises(ValueError, match="provider/location"):
        ArtifactAcquisitionResult(**(values | {"storage_provider_id": " "}))
    with pytest.raises(ValueError, match="sha1 must be lowercase"):
        ArtifactAcquisitionResult(**(values | {"sha1": result.sha1.upper()}))
    with pytest.raises(TypeError, match="downloaded must be bool"):
        ArtifactAcquisitionResult(**(values | {"downloaded": 1}))
    with pytest.raises(ValueError, match="size must be a non-negative integer"):
        ArtifactAcquisitionResult(**(values | {"size": True}))
