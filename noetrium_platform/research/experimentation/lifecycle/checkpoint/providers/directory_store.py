from __future__ import annotations

import hashlib
from contextlib import ExitStack
from pathlib import Path

from noetrium_platform.research.execution.api import ParticipantCheckpoint
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    InterprocessFileLock,
    atomic_replace_bytes,
    durable_publish_immutable_bytes,
    durable_unlink,
    fsync_directory,
    sha256_file,
)
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    decode_checksummed_document,
    encode_checksummed_document,
)

from .codec import RunCheckpointManifestCodec
from .workload_codec import WorkloadCheckpointManifestCodec
from .publication_intent import (
    CheckpointPublicationIntent,
    CheckpointPublicationIntentConflict,
    CheckpointPublicationIntentCorruptionError,
    DirectoryCheckpointPublicationIntentStore,
)
from ..api.contracts import (
    RunCheckpointBundle,
    RunCheckpointConflict,
    RunCheckpointGcAssessment,
    RunCheckpointIntegrityError,
    RunCheckpointManifest,
    RunCheckpointPersistenceState,
    RunCheckpointRecoveryRequired,
    RunCheckpointStore,
    RunParticipantPayload,
)


class DirectoryRunCheckpointStore(RunCheckpointStore):
    """Crash-durable content-addressed persistence for generic participant checkpoints."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.blob_locks = self.root / "blob_locks"
        self.blob_staging = self.root / "blob_staging"
        self.manifests = self.root / "manifests"
        self.manifest_locks = self.root / "manifest_locks"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.blob_locks.mkdir(parents=True, exist_ok=True)
        self.blob_staging.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        self.manifest_locks.mkdir(parents=True, exist_ok=True)
        self.codec = RunCheckpointManifestCodec()
        self._intents = DirectoryCheckpointPublicationIntentStore(
            self.root,
            namespace="run",
        )

    @staticmethod
    def _sha(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / f"{digest}.bin"

    def _blob_lock_path(self, digest: str) -> Path:
        return self.blob_locks / f"{digest}.lock"

    def _verify_blob(
        self,
        path: Path,
        *,
        expected_digest: str,
        expected_size: int,
    ) -> None:
        try:
            stored_digest, stored_size = sha256_file(path)
        except OSError as exc:
            raise RunCheckpointIntegrityError(
                f"checkpoint blob cannot be verified: {expected_digest}"
            ) from exc
        if (
            stored_digest != expected_digest
            or stored_size != expected_size
        ):
            raise RunCheckpointIntegrityError(
                f"corrupt existing checkpoint blob: {expected_digest}"
            )

    def _cleanup_blob_staging(self, path: Path) -> None:
        # A hard kill may strand only a non-canonical staging file. Exact
        # retry under the digest lock is the recovery authority: discard stale
        # staging and reconstruct from the verified caller payload.
        for candidate in tuple(
            sorted(self.blob_staging.glob(f"{path.name}.immutable.*"))
        ):
            durable_unlink(candidate)

    def _manifest_path(self, checkpoint_id: str) -> Path:
        safe = hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest()
        return self.manifests / f"{safe}.json"

    def _manifest_lock_path(self, checkpoint_id: str) -> Path:
        safe = hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest()
        return self.manifest_locks / f"{safe}.lock"

    def _publication_intent(
        self,
        manifest: RunCheckpointManifest,
        encoded: bytes,
        participant_payloads: tuple[RunParticipantPayload, ...],
    ) -> CheckpointPublicationIntent:
        return CheckpointPublicationIntent(
            namespace="run",
            checkpoint_id=manifest.checkpoint_id,
            manifest_sha256=self._intents.manifest_digest(encoded),
            blob_sha256s=tuple(
                sorted(
                    {
                        item.checkpoint.ref.payload_sha256
                        for item in participant_payloads
                    }
                )
            ),
        )

    def _publish_intent(
        self,
        intent: CheckpointPublicationIntent,
    ) -> None:
        try:
            self._intents.publish(intent)
        except CheckpointPublicationIntentConflict as exc:
            raise RunCheckpointConflict(str(exc)) from exc
        except CheckpointPublicationIntentCorruptionError as exc:
            raise RunCheckpointIntegrityError(str(exc)) from exc

    def _clear_intent(
        self,
        intent: CheckpointPublicationIntent,
        *,
        manifest_committed: bool,
    ) -> None:
        try:
            self._intents.clear(intent)
        except CheckpointPublicationIntentConflict as exc:
            if manifest_committed:
                raise RunCheckpointIntegrityError(
                    "committed checkpoint has conflicting publication intent"
                ) from exc
            raise RunCheckpointConflict(str(exc)) from exc
        except CheckpointPublicationIntentCorruptionError as exc:
            raise RunCheckpointIntegrityError(str(exc)) from exc

    def _write_blob_under_lock(
        self,
        payload: bytes,
        expected_digest: str,
    ) -> None:
        actual = self._sha(payload)
        if actual != expected_digest:
            raise RunCheckpointIntegrityError(
                f"checkpoint payload digest mismatch: expected={expected_digest} actual={actual}"
            )
        path = self._blob_path(actual)
        self._cleanup_blob_staging(path)
        if path.exists():
            self._verify_blob(
                path,
                expected_digest=actual,
                expected_size=len(payload),
            )
            fsync_directory(path.parent)
            return

        try:
            durable_publish_immutable_bytes(
                path,
                payload,
                staging_dir=self.blob_staging,
            )
        except FileExistsError:
            self._verify_blob(
                path,
                expected_digest=actual,
                expected_size=len(payload),
            )
            fsync_directory(path.parent)
            return
        self._verify_blob(
            path,
            expected_digest=actual,
            expected_size=len(payload),
        )

    def _write_blob(self, payload: bytes, expected_digest: str) -> None:
        with InterprocessFileLock(self._blob_lock_path(expected_digest)):
            self._write_blob_under_lock(payload, expected_digest)

    def publish(
        self,
        manifest: RunCheckpointManifest,
        participant_payloads: tuple[RunParticipantPayload, ...],
    ) -> RunCheckpointManifest:
        try:
            RunCheckpointBundle(manifest, participant_payloads)
        except (TypeError, ValueError) as exc:
            raise RunCheckpointIntegrityError(
                "participant payload refs do not match checkpoint manifest"
            ) from exc
        path = self._manifest_path(manifest.checkpoint_id)
        encoded = self.codec.encode(manifest)
        intent = self._publication_intent(
            manifest,
            encoded,
            participant_payloads,
        )
        with InterprocessFileLock(
            self._manifest_lock_path(manifest.checkpoint_id)
        ):
            if path.exists():
                current = self.codec.decode(path.read_bytes())
                if current != manifest:
                    raise RunCheckpointConflict(
                        "checkpoint id is already bound to different state: "
                        f"{manifest.checkpoint_id}"
                    )
                # A crash may have committed the manifest before clearing its
                # intent. Exact idempotent retry converges that final step.
                self._clear_intent(intent, manifest_committed=True)
                return current

            # Keep every referenced CAS generation fenced until the manifest
            # commit and intent clear converge. GC uses the same per-digest
            # locks, so it can never miss a publication in the gap between
            # blob creation and manifest visibility.
            digests = tuple(
                sorted(
                    {
                        item.checkpoint.ref.payload_sha256
                        for item in participant_payloads
                    }
                )
            )
            with ExitStack() as blob_locks:
                for digest in digests:
                    blob_locks.enter_context(
                        InterprocessFileLock(self._blob_lock_path(digest))
                    )
                # Publish durable ownership before any content blob. A crash
                # after this point leaves a typed pending publication.
                self._publish_intent(intent)
                for item in participant_payloads:
                    self._write_blob_under_lock(
                        item.checkpoint.opaque_payload,
                        item.checkpoint.ref.payload_sha256,
                    )
                atomic_replace_bytes(path, encoded)
                self._clear_intent(intent, manifest_committed=True)
                return manifest

    def load(self, checkpoint_id: str) -> RunCheckpointBundle:
        path = self._manifest_path(checkpoint_id)
        try:
            pending = self._intents.load(checkpoint_id)
        except CheckpointPublicationIntentCorruptionError as exc:
            raise RunCheckpointIntegrityError(
                "pending checkpoint publication intent is corrupt"
            ) from exc
        if not path.exists():
            if pending is not None:
                raise RunCheckpointRecoveryRequired(
                    checkpoint_id,
                    namespace=pending.namespace,
                    manifest_sha256=pending.manifest_sha256,
                    blob_sha256s=pending.blob_sha256s,
                )
            raise FileNotFoundError(f"study checkpoint not found: {checkpoint_id}")

        encoded = path.read_bytes()
        manifest = self.codec.decode(encoded)
        if manifest.checkpoint_id != checkpoint_id:
            raise RunCheckpointIntegrityError("checkpoint lookup identity mismatch")
        if pending is not None:
            committed_intent = CheckpointPublicationIntent(
                namespace=self._intents.namespace,
                checkpoint_id=manifest.checkpoint_id,
                manifest_sha256=self._intents.manifest_digest(encoded),
                blob_sha256s=tuple(
                    sorted(
                        {
                            ref.checkpoint.payload_sha256
                            for ref in manifest.participant_snapshots
                        }
                    )
                ),
            )
            if pending != committed_intent:
                raise RunCheckpointIntegrityError(
                    "committed checkpoint conflicts with pending publication intent"
                )
        participants: list[RunParticipantPayload] = []
        for ref in manifest.participant_snapshots:
            checkpoint_ref = ref.checkpoint
            payload = self._blob_path(checkpoint_ref.payload_sha256).read_bytes()
            if self._sha(payload) != checkpoint_ref.payload_sha256:
                raise RunCheckpointIntegrityError(
                    f"participant checkpoint blob checksum mismatch: {ref.role}"
                )
            participants.append(RunParticipantPayload(ref, ParticipantCheckpoint(checkpoint_ref, payload)))
        return RunCheckpointBundle(manifest, tuple(participants))


__all__ = ["DirectoryRunCheckpointStore"]
