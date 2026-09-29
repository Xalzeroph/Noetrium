from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Iterator

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobFencePort,
    ArtifactBlobGcAssessment,
    ArtifactBlobGeneration,
    ArtifactBlobLifecyclePort,
    ArtifactBlobLifecycleState,
    ArtifactBlobRef,
    ArtifactBlobStoreError,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    require_sha256,
)
from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    atomic_replace_bytes_many,
    durable_publish_immutable_bytes_many,
    durable_unlink,
    fsync_directory,
)
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)


_LIFECYCLE_SCHEMA = "artifact.blob-generation.v1"
_LIFECYCLE_FIELDS = {
    "content_sha256",
    "generation",
    "state",
    "size_bytes",
    "gc_proof_digest",
}


@dataclass(frozen=True, slots=True)
class _BlobLifecycleRecord:
    content_sha256: str
    generation: int
    state: ArtifactBlobLifecycleState
    size_bytes: int
    gc_proof_digest: str | None = None

    def __post_init__(self) -> None:
        require_sha256(self.content_sha256, "artifact blob lifecycle digest")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation <= 0
        ):
            raise ValueError("artifact blob lifecycle generation must be positive")
        if type(self.state) is not ArtifactBlobLifecycleState:
            raise TypeError("artifact blob lifecycle state must be typed")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("artifact blob lifecycle size must be non-negative")
        if self.gc_proof_digest is not None:
            require_sha256(
                self.gc_proof_digest,
                "artifact blob lifecycle gc_proof_digest",
            )
        if (
            self.state is ArtifactBlobLifecycleState.ACTIVE
            and self.gc_proof_digest is not None
        ):
            raise ValueError("active blob lifecycle cannot retain a GC proof")
        if (
            self.state is not ArtifactBlobLifecycleState.ACTIVE
            and self.gc_proof_digest is None
        ):
            raise ValueError("retiring/purged blob lifecycle requires GC proof")

    def generation_view(self) -> ArtifactBlobGeneration:
        return ArtifactBlobGeneration(
            self.content_sha256,
            self.generation,
            self.state,
            self.gc_proof_digest,
        )

    def document(self) -> dict[str, object]:
        return {
            "content_sha256": self.content_sha256,
            "generation": self.generation,
            "state": self.state.value,
            "size_bytes": self.size_bytes,
            "gc_proof_digest": self.gc_proof_digest,
        }


@dataclass(slots=True)
class _DirectoryArtifactBlobFence(ArtifactBlobFencePort):
    _store: "DirectoryArtifactBlobStore"
    ref: ArtifactBlobRef
    generation: ArtifactBlobGeneration

    def read(self) -> bytes:
        if self.generation.state is not ArtifactBlobLifecycleState.ACTIVE:
            raise ArtifactBlobStoreError(
                "artifact blob generation is not active"
            )
        return self._store._read_ref_payload_unlocked(self.ref)

    def assess_gc(
        self,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> ArtifactBlobGcAssessment:
        return self._store._assess_gc_under_lock(
            self.ref,
            closures=closures,
        )

    def purge(
        self,
        *,
        gc: ArtifactBlobGcAssessment,
    ) -> ArtifactBlobGeneration:
        result = self._store._purge_under_lock(
            self.ref,
            gc=gc,
        )
        self.generation = result
        return result


class DirectoryArtifactBlobStore(
    ArtifactBlobStorePort,
    ArtifactBlobLifecyclePort,
):
    durability = "crash_durable"

    _LOCK_SHARDS = 256
    _VERIFY_CHUNK_BYTES = 1024 * 1024

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_root = self.root / ".locks"
        self._staging_root = self.root / ".staging"
        self._lifecycle_root = self.root / ".lifecycle"
        self._lock_root.mkdir(parents=True, exist_ok=True)
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._lifecycle_root.mkdir(parents=True, exist_ok=True)
        self._local_locks = tuple(
            RLock() for _ in range(self._LOCK_SHARDS)
        )

    @staticmethod
    def _digest(payload: bytes) -> str:
        return sha256(payload).hexdigest()

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}.blob"

    def _lifecycle_path(self, digest: str) -> Path:
        return self._lifecycle_root / f"{digest}.json"

    @staticmethod
    def _shard_index(digest: str) -> int:
        return int(digest[:2], 16)

    def _lock_path(self, digest: str) -> Path:
        return self._lock_root / f"{digest[:2]}.lock"

    def _verify_existing(
        self,
        path: Path,
        payload: bytes,
        digest: str,
    ) -> None:
        hasher = sha256()
        offset = 0
        identical = True
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(self._VERIFY_CHUNK_BYTES)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    end = offset + len(chunk)
                    if payload[offset:end] != chunk:
                        identical = False
                    offset = end
        except OSError as exc:
            raise ArtifactBlobStoreError(
                "existing artifact blob cannot be read"
            ) from exc
        if offset != len(payload) or hasher.hexdigest() != digest:
            raise ArtifactBlobStoreError(
                "existing artifact blob failed integrity verification"
            )
        if not identical:
            raise ArtifactBlobStoreError(
                "artifact blob digest collision"
            )

    def _read_ref_payload_unlocked(self, ref: ArtifactBlobRef) -> bytes:
        try:
            payload = self._path(ref.content_sha256).read_bytes()
        except OSError as exc:
            raise ArtifactBlobStoreError("artifact blob is missing") from exc
        if (
            len(payload) != ref.size_bytes
            or self._digest(payload) != ref.content_sha256
        ):
            raise ArtifactBlobStoreError("artifact blob integrity mismatch")
        return payload

    def _cleanup_staging(self, path: Path) -> None:
        for candidate in tuple(
            sorted(self._staging_root.glob(f"{path.name}.immutable.*"))
        ):
            durable_unlink(candidate)

    def _read_lifecycle_unlocked(
        self,
        digest: str,
    ) -> _BlobLifecycleRecord | None:
        path = self._lifecycle_path(digest)
        if not path.exists():
            return None
        try:
            payload = decode_checksummed_document(
                path.read_bytes(),
                expected_schema=_LIFECYCLE_SCHEMA,
            ).payload
            if set(payload) != _LIFECYCLE_FIELDS:
                raise ValueError("artifact blob lifecycle fields drifted")
            record = _BlobLifecycleRecord(
                content_sha256=str(payload["content_sha256"]),
                generation=payload["generation"],
                state=ArtifactBlobLifecycleState(str(payload["state"])),
                size_bytes=payload["size_bytes"],
                gc_proof_digest=payload["gc_proof_digest"],
            )
            if record.content_sha256 != digest:
                raise ValueError("artifact blob lifecycle identity drifted")
            if path.name != f"{digest}.json":
                raise ValueError("artifact blob lifecycle filename drifted")
            return record
        except (
            ChecksummedDocumentError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise ArtifactBlobStoreError(
                "artifact blob lifecycle metadata is corrupt"
            ) from exc

    def _write_lifecycle_unlocked(
        self,
        record: _BlobLifecycleRecord,
    ) -> None:
        atomic_replace_bytes(
            self._lifecycle_path(record.content_sha256),
            encode_checksummed_document(
                _LIFECYCLE_SCHEMA,
                record.document(),
            ),
        )

    def _active_record_for_publish_unlocked(
        self,
        ref: ArtifactBlobRef,
    ) -> _BlobLifecycleRecord:
        current = self._read_lifecycle_unlocked(ref.content_sha256)
        path = self._path(ref.content_sha256)
        if current is None:
            active = _BlobLifecycleRecord(
                ref.content_sha256,
                1,
                ArtifactBlobLifecycleState.ACTIVE,
                ref.size_bytes,
            )
            self._write_lifecycle_unlocked(active)
            return active
        if current.size_bytes != ref.size_bytes:
            raise ArtifactBlobStoreError(
                "artifact blob lifecycle size conflicts with content identity"
            )
        if current.state is ArtifactBlobLifecycleState.ACTIVE:
            return current
        if current.state is ArtifactBlobLifecycleState.RETIRING:
            raise ArtifactBlobStoreError(
                "artifact blob retirement requires recovery before republish"
            )
        if path.exists():
            raise ArtifactBlobStoreError(
                "purged artifact blob has unexpected physical residue"
            )
        active = _BlobLifecycleRecord(
            ref.content_sha256,
            current.generation + 1,
            ArtifactBlobLifecycleState.ACTIVE,
            ref.size_bytes,
        )
        self._write_lifecycle_unlocked(active)
        return active

    def _generation_under_lock(
        self,
        ref: ArtifactBlobRef,
    ) -> ArtifactBlobGeneration:
        current = self._read_lifecycle_unlocked(ref.content_sha256)
        path = self._path(ref.content_sha256)
        if current is None:
            self._read_ref_payload_unlocked(ref)
            current = _BlobLifecycleRecord(
                ref.content_sha256,
                1,
                ArtifactBlobLifecycleState.ACTIVE,
                ref.size_bytes,
            )
            self._write_lifecycle_unlocked(current)
            return current.generation_view()
        if current.size_bytes != ref.size_bytes:
            raise ArtifactBlobStoreError(
                "artifact blob ref size does not match physical generation"
            )
        if current.state is ArtifactBlobLifecycleState.ACTIVE:
            self._read_ref_payload_unlocked(ref)
        elif current.state is ArtifactBlobLifecycleState.RETIRING:
            if path.exists():
                self._read_ref_payload_unlocked(ref)
        else:
            if path.exists():
                raise ArtifactBlobStoreError(
                    "purged artifact blob has unexpected physical residue"
                )
        return current.generation_view()

    @contextmanager
    def publish_fenced(
        self,
        payload: bytes,
        *,
        media_type: str,
    ) -> Iterator[ArtifactBlobRef]:
        ref = self.put_many(((payload, media_type),))[0]
        with self.fence(ref):
            yield ref

    @contextmanager
    def fence(
        self,
        ref: ArtifactBlobRef,
    ) -> Iterator[ArtifactBlobFencePort]:
        if type(ref) is not ArtifactBlobRef:
            raise TypeError("artifact blob ref must be ArtifactBlobRef")
        digest = ref.content_sha256
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                generation = self._generation_under_lock(ref)
                yield _DirectoryArtifactBlobFence(self, ref, generation)

    def put_many(
        self,
        items: tuple[tuple[bytes, str], ...],
    ) -> tuple[ArtifactBlobRef, ...]:
        if type(items) is not tuple:
            raise TypeError("artifact blob put_many requires tuple")
        if not items:
            return ()

        refs: list[ArtifactBlobRef] = []
        payload_by_digest: dict[str, bytes] = {}
        ref_by_digest: dict[str, ArtifactBlobRef] = {}
        for item in items:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError(
                    "artifact blob put_many item must be (payload, media_type)"
                )
            payload, media_type = item
            if type(payload) is not bytes:
                raise TypeError("artifact blob payload must be bytes")
            if type(media_type) is not str or not media_type.strip():
                raise ValueError("artifact blob media_type must be non-empty")
            digest = self._digest(payload)
            ref = ArtifactBlobRef(digest, len(payload), media_type)
            previous = payload_by_digest.get(digest)
            if previous is not None and previous != payload:
                raise ArtifactBlobStoreError("artifact blob digest collision")
            payload_by_digest[digest] = payload
            ref_by_digest.setdefault(digest, ref)
            refs.append(ref)

        digests = tuple(sorted(payload_by_digest))
        shards = tuple(sorted({self._shard_index(digest) for digest in digests}))
        lifecycle_updates: list[tuple[Path, bytes]] = []
        missing_blobs: list[tuple[Path, bytes]] = []

        with ExitStack() as stack:
            for shard in shards:
                stack.enter_context(self._local_locks[shard])
            for shard in shards:
                stack.enter_context(
                    InterprocessFileLock(
                        self._lock_root / f"{shard:02x}.lock"
                    )
                )

            for digest in digests:
                payload = payload_by_digest[digest]
                ref = ref_by_digest[digest]
                path = self._path(digest)
                current = self._read_lifecycle_unlocked(digest)

                if current is None:
                    lifecycle = _BlobLifecycleRecord(
                        digest,
                        1,
                        ArtifactBlobLifecycleState.ACTIVE,
                        ref.size_bytes,
                    )
                    lifecycle_updates.append(
                        (
                            self._lifecycle_path(digest),
                            encode_checksummed_document(
                                _LIFECYCLE_SCHEMA,
                                lifecycle.document(),
                            ),
                        )
                    )
                else:
                    if current.size_bytes != ref.size_bytes:
                        raise ArtifactBlobStoreError(
                            "artifact blob lifecycle size conflicts with content identity"
                        )
                    if current.state is ArtifactBlobLifecycleState.RETIRING:
                        raise ArtifactBlobStoreError(
                            "artifact blob retirement requires recovery before republish"
                        )
                    if current.state is ArtifactBlobLifecycleState.PURGED:
                        if path.exists():
                            raise ArtifactBlobStoreError(
                                "purged artifact blob has unexpected physical residue"
                            )
                        lifecycle = _BlobLifecycleRecord(
                            digest,
                            current.generation + 1,
                            ArtifactBlobLifecycleState.ACTIVE,
                            ref.size_bytes,
                        )
                        lifecycle_updates.append(
                            (
                                self._lifecycle_path(digest),
                                encode_checksummed_document(
                                    _LIFECYCLE_SCHEMA,
                                    lifecycle.document(),
                                ),
                            )
                        )

                self._cleanup_staging(path)
                if not path.exists():
                    missing_blobs.append((path, payload))

            if missing_blobs:
                try:
                    durable_publish_immutable_bytes_many(
                        tuple(missing_blobs),
                        staging_dir=self._staging_root,
                    )
                except FileExistsError:
                    # A non-cooperating external immutable publisher may win the
                    # no-replace race. Verification below is the authority: exact
                    # bytes are accepted, any mismatch fails closed.
                    pass

            for digest in digests:
                self._verify_existing(
                    self._path(digest),
                    payload_by_digest[digest],
                    digest,
                )

            if lifecycle_updates:
                atomic_replace_bytes_many(tuple(lifecycle_updates))

        return tuple(refs)

    def put(self, payload: bytes, *, media_type: str) -> ArtifactBlobRef:
        return self.put_many(((payload, media_type),))[0]

    def resolve(
        self,
        content_sha256: str,
        *,
        media_type: str,
    ) -> ArtifactBlobRef:
        require_sha256(
            content_sha256,
            "artifact blob resolver content_sha256",
        )
        if type(media_type) is not str or not media_type.strip():
            raise ValueError(
                "artifact blob resolver media_type must be non-empty"
            )
        digest = content_sha256
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                lifecycle = self._read_lifecycle_unlocked(digest)
                if lifecycle is not None and (
                    lifecycle.state is not ArtifactBlobLifecycleState.ACTIVE
                ):
                    raise ArtifactBlobStoreError(
                        "artifact blob generation is not active"
                    )
                path = self._path(digest)
                try:
                    size_bytes = path.stat().st_size
                except OSError as exc:
                    raise ArtifactBlobStoreError(
                        "artifact blob is missing"
                    ) from exc
                ref = ArtifactBlobRef(
                    digest,
                    size_bytes,
                    media_type,
                )
                self._read_ref_payload_unlocked(ref)
                if lifecycle is None:
                    self._write_lifecycle_unlocked(
                        _BlobLifecycleRecord(
                            digest,
                            1,
                            ArtifactBlobLifecycleState.ACTIVE,
                            size_bytes,
                        )
                    )
                elif lifecycle.size_bytes != size_bytes:
                    raise ArtifactBlobStoreError(
                        "artifact blob lifecycle size drifted"
                    )
                return ref

    def get(self, ref: ArtifactBlobRef) -> bytes:
        if type(ref) is not ArtifactBlobRef:
            raise TypeError("artifact blob ref must be ArtifactBlobRef")
        digest = ref.content_sha256
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                lifecycle = self._read_lifecycle_unlocked(digest)
                if lifecycle is not None and (
                    lifecycle.state is not ArtifactBlobLifecycleState.ACTIVE
                ):
                    raise ArtifactBlobStoreError(
                        "artifact blob generation is not active"
                    )
                payload = self._read_ref_payload_unlocked(ref)
                if lifecycle is None:
                    self._write_lifecycle_unlocked(
                        _BlobLifecycleRecord(
                            digest,
                            1,
                            ArtifactBlobLifecycleState.ACTIVE,
                            ref.size_bytes,
                        )
                    )
                elif lifecycle.size_bytes != ref.size_bytes:
                    raise ArtifactBlobStoreError(
                        "artifact blob lifecycle size drifted"
                    )
                return payload

    def verify(self, ref: ArtifactBlobRef) -> bool:
        try:
            self.get(ref)
        except ArtifactBlobStoreError:
            return False
        return True

    def generation(
        self,
        ref: ArtifactBlobRef,
    ) -> ArtifactBlobGeneration:
        if type(ref) is not ArtifactBlobRef:
            raise TypeError("artifact blob ref must be ArtifactBlobRef")
        digest = ref.content_sha256
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                return self._generation_under_lock(ref)

    def _assess_gc_under_lock(
        self,
        ref: ArtifactBlobRef,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> ArtifactBlobGcAssessment:
        generation = self._generation_under_lock(ref)
        return ArtifactBlobGcAssessment(
            content_sha256=ref.content_sha256,
            size_bytes=ref.size_bytes,
            generation=generation.generation,
            closures=closures,
        )

    @staticmethod
    def _require_gc(
        ref: ArtifactBlobRef,
        gc: ArtifactBlobGcAssessment,
    ) -> ArtifactBlobGcAssessment:
        if type(gc) is not ArtifactBlobGcAssessment:
            raise RuntimeError(
                "artifact blob physical GC requires a typed GC assessment"
            )
        if (
            gc.content_sha256 != ref.content_sha256
            or gc.size_bytes != ref.size_bytes
        ):
            raise RuntimeError(
                "artifact blob GC assessment does not bind the exact content identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "artifact blob physical GC requires complete execution, evidence, "
                "and recovery closure with zero retained references"
            )
        return gc

    def _purge_under_lock(
        self,
        ref: ArtifactBlobRef,
        *,
        gc: ArtifactBlobGcAssessment,
    ) -> ArtifactBlobGeneration:
        gc = self._require_gc(ref, gc)
        expected_generation = gc.generation
        gc_proof_digest = gc.proof_digest
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation <= 0
        ):
            raise ValueError(
                "artifact blob purge expected_generation must be positive"
            )
        require_sha256(
            gc_proof_digest,
            "artifact blob purge gc_proof_digest",
        )
        current = self._read_lifecycle_unlocked(ref.content_sha256)
        if current is None:
            self._read_ref_payload_unlocked(ref)
            current = _BlobLifecycleRecord(
                ref.content_sha256,
                1,
                ArtifactBlobLifecycleState.ACTIVE,
                ref.size_bytes,
            )
            self._write_lifecycle_unlocked(current)
        if current.size_bytes != ref.size_bytes:
            raise ArtifactBlobStoreError(
                "artifact blob purge ref size drifted"
            )
        if current.generation != expected_generation:
            raise ArtifactBlobStoreError(
                "stale artifact blob generation cannot purge replacement"
            )

        path = self._path(ref.content_sha256)
        if current.state is ArtifactBlobLifecycleState.ACTIVE:
            self._read_ref_payload_unlocked(ref)
            current = _BlobLifecycleRecord(
                current.content_sha256,
                current.generation,
                ArtifactBlobLifecycleState.RETIRING,
                current.size_bytes,
                gc_proof_digest,
            )
            self._write_lifecycle_unlocked(current)
        elif current.gc_proof_digest != gc_proof_digest:
            raise ArtifactBlobStoreError(
                "artifact blob GC proof changed across retirement retry"
            )

        if current.state is ArtifactBlobLifecycleState.PURGED:
            if path.exists():
                raise ArtifactBlobStoreError(
                    "purged artifact blob has unexpected physical residue"
                )
            return current.generation_view()

        self._cleanup_staging(path)
        if path.exists():
            self._read_ref_payload_unlocked(ref)
            durable_unlink(path)
        current = _BlobLifecycleRecord(
            current.content_sha256,
            current.generation,
            ArtifactBlobLifecycleState.PURGED,
            current.size_bytes,
            gc_proof_digest,
        )
        self._write_lifecycle_unlocked(current)
        return current.generation_view()

    def assess_gc(
        self,
        ref: ArtifactBlobRef,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> ArtifactBlobGcAssessment:
        if type(ref) is not ArtifactBlobRef:
            raise TypeError("artifact blob ref must be ArtifactBlobRef")
        digest = ref.content_sha256
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                return self._assess_gc_under_lock(
                    ref,
                    closures=closures,
                )

    def purge(
        self,
        ref: ArtifactBlobRef,
        *,
        gc: ArtifactBlobGcAssessment,
    ) -> ArtifactBlobGeneration:
        if type(ref) is not ArtifactBlobRef:
            raise TypeError("artifact blob ref must be ArtifactBlobRef")
        digest = ref.content_sha256
        local_lock = self._local_locks[self._shard_index(digest)]
        with local_lock:
            with InterprocessFileLock(self._lock_path(digest)):
                return self._purge_under_lock(ref, gc=gc)


__all__ = ["DirectoryArtifactBlobStore"]
