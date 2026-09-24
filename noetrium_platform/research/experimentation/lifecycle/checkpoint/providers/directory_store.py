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
    CheckpointGcAssessment,
    CheckpointNamespace,
    CheckpointPersistenceState,
    RunCheckpointConflict,
    RunCheckpointIntegrityError,
    RunCheckpointManifest,
    RunCheckpointRecoveryRequired,
    RunCheckpointStore,
    RunParticipantPayload,
)


_RETIREMENT_SCHEMA = "noetrium.checkpoint-retirement.v1"
_RETIREMENT_FIELDS = {
    "namespace",
    "checkpoint_id",
    "persistence_state",
    "state_digest",
    "blob_sha256s",
    "gc_proof_digest",
    "purged",
}


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
        self.retired = self.root / "retired"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.blob_locks.mkdir(parents=True, exist_ok=True)
        self.blob_staging.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        self.manifest_locks.mkdir(parents=True, exist_ok=True)
        self.retired.mkdir(parents=True, exist_ok=True)
        self.codec = RunCheckpointManifestCodec()
        self._workload_codec = WorkloadCheckpointManifestCodec()
        self._intents = DirectoryCheckpointPublicationIntentStore(
            self.root,
            namespace="run",
        )
        self._workload_intents = DirectoryCheckpointPublicationIntentStore(
            self.root,
            namespace="workload",
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

    def _retirement_path(self, checkpoint_id: str) -> Path:
        safe = hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest()
        return self.retired / f"{safe}.json"

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

    @staticmethod
    def _gc_state_digest(
        checkpoint_id: str,
        persistence_state: CheckpointPersistenceState,
        manifest_sha256: str,
        blob_sha256s: tuple[str, ...],
    ) -> str:
        return canonical_digest(
            {
                "schema": "noetrium.checkpoint-persistence-state.v1",
                "namespace": CheckpointNamespace.RUN.value,
                "checkpoint_id": checkpoint_id,
                "persistence_state": persistence_state.value,
                "manifest_sha256": manifest_sha256,
                "blob_sha256s": list(blob_sha256s),
            }
        )

    def _current_gc_state_unlocked(
        self,
        checkpoint_id: str,
    ) -> tuple[CheckpointPersistenceState, str, tuple[str, ...]]:
        path = self._manifest_path(checkpoint_id)
        try:
            pending = self._intents.load(checkpoint_id)
        except CheckpointPublicationIntentCorruptionError as exc:
            raise RunCheckpointIntegrityError(
                "pending checkpoint publication intent is corrupt"
            ) from exc

        if path.exists():
            encoded = path.read_bytes()
            manifest = self.codec.decode(encoded)
            if manifest.checkpoint_id != checkpoint_id:
                raise RunCheckpointIntegrityError(
                    "checkpoint manifest identity mismatch during GC assessment"
                )
            blobs = tuple(
                sorted(
                    {
                        ref.checkpoint.payload_sha256
                        for ref in manifest.participant_snapshots
                    }
                )
            )
            manifest_sha256 = self._sha(encoded)
            if pending is not None:
                expected = CheckpointPublicationIntent(
                    namespace=self._intents.namespace,
                    checkpoint_id=checkpoint_id,
                    manifest_sha256=manifest_sha256,
                    blob_sha256s=blobs,
                )
                if pending != expected:
                    raise RunCheckpointIntegrityError(
                        "committed checkpoint conflicts with pending publication intent"
                    )
            return (
                CheckpointPersistenceState.COMMITTED,
                self._gc_state_digest(
                    checkpoint_id,
                    CheckpointPersistenceState.COMMITTED,
                    manifest_sha256,
                    blobs,
                ),
                blobs,
            )

        if pending is not None:
            return (
                CheckpointPersistenceState.PENDING,
                self._gc_state_digest(
                    checkpoint_id,
                    CheckpointPersistenceState.PENDING,
                    pending.manifest_sha256,
                    pending.blob_sha256s,
                ),
                pending.blob_sha256s,
            )
        raise FileNotFoundError(
            f"checkpoint persistence state not found: {checkpoint_id}"
        )

    @staticmethod
    def _retirement_document(
        gc: CheckpointGcAssessment,
        *,
        purged: bool,
    ) -> dict[str, object]:
        return {
            "namespace": gc.namespace.value,
            "checkpoint_id": gc.checkpoint_id,
            "persistence_state": gc.persistence_state.value,
            "state_digest": gc.state_digest,
            "blob_sha256s": list(gc.blob_sha256s),
            "gc_proof_digest": gc.proof_digest,
            "purged": purged,
        }

    def _write_retirement(
        self,
        gc: CheckpointGcAssessment,
        *,
        purged: bool,
    ) -> None:
        atomic_replace_bytes(
            self._retirement_path(gc.checkpoint_id),
            encode_checksummed_document(
                _RETIREMENT_SCHEMA,
                self._retirement_document(gc, purged=purged),
            ),
        )

    def _read_retirement(
        self,
        checkpoint_id: str,
    ) -> dict[str, object] | None:
        path = self._retirement_path(checkpoint_id)
        if not path.exists():
            return None
        try:
            payload = decode_checksummed_document(
                path.read_bytes(),
                expected_schema=_RETIREMENT_SCHEMA,
            ).payload
        except (OSError, ChecksummedDocumentError) as exc:
            raise RunCheckpointIntegrityError(
                "checkpoint retirement document is corrupt"
            ) from exc
        if set(payload) != _RETIREMENT_FIELDS:
            raise RunCheckpointIntegrityError(
                "checkpoint retirement document fields drifted"
            )
        try:
            if payload["namespace"] != CheckpointNamespace.RUN.value:
                raise ValueError("checkpoint retirement namespace drifted")
            if payload["checkpoint_id"] != checkpoint_id:
                raise ValueError("checkpoint retirement identity drifted")
            CheckpointPersistenceState(str(payload["persistence_state"]))
            for label in ("state_digest", "gc_proof_digest"):
                value = payload[label]
                if (
                    type(value) is not str
                    or len(value) != 64
                    or any(ch not in "0123456789abcdef" for ch in value)
                ):
                    raise ValueError(f"invalid retirement {label}")
            blobs = payload["blob_sha256s"]
            if (
                not isinstance(blobs, list)
                or any(
                    type(value) is not str
                    or len(value) != 64
                    or any(ch not in "0123456789abcdef" for ch in value)
                    for value in blobs
                )
                or tuple(blobs) != tuple(sorted(set(blobs)))
            ):
                raise ValueError("invalid retirement blob_sha256s")
            if type(payload["purged"]) is not bool:
                raise TypeError("retirement purged must be bool")
        except (TypeError, ValueError) as exc:
            raise RunCheckpointIntegrityError(
                "checkpoint retirement document payload is invalid"
            ) from exc
        return payload

    @staticmethod
    def _manifest_filename(checkpoint_id: str) -> str:
        return hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest() + ".json"

    def _blob_referenced_elsewhere(
        self,
        digest: str,
        *,
        excluding_run_checkpoint_id: str | None = None,
        excluding_workload_checkpoint_id: str | None = None,
    ) -> bool:
        for path in sorted(self.manifests.glob("*.json")):
            manifest = self.codec.decode(path.read_bytes())
            if path.name != self._manifest_filename(manifest.checkpoint_id):
                raise RunCheckpointIntegrityError(
                    "run checkpoint manifest filename identity mismatch"
                )
            if (
                excluding_run_checkpoint_id is not None
                and manifest.checkpoint_id == excluding_run_checkpoint_id
            ):
                continue
            if any(
                ref.checkpoint.payload_sha256 == digest
                for ref in manifest.participant_snapshots
            ):
                return True

        workload_root = self.root / "workload_manifests"
        for path in sorted(workload_root.glob("*.json")):
            manifest = self._workload_codec.decode(path.read_bytes())
            if path.name != self._manifest_filename(manifest.checkpoint_id):
                raise RunCheckpointIntegrityError(
                    "workload checkpoint manifest filename identity mismatch"
                )
            if (
                excluding_workload_checkpoint_id is not None
                and manifest.checkpoint_id == excluding_workload_checkpoint_id
            ):
                continue
            if any(
                ref.payload_sha256 == digest
                for ref in manifest.component_refs
            ):
                return True

        try:
            run_intents = self._intents.all()
            workload_intents = self._workload_intents.all()
        except CheckpointPublicationIntentCorruptionError as exc:
            raise RunCheckpointIntegrityError(
                "checkpoint publication intent set is corrupt"
            ) from exc

        if any(
            (
                excluding_run_checkpoint_id is None
                or intent.checkpoint_id != excluding_run_checkpoint_id
            )
            and digest in intent.blob_sha256s
            for intent in run_intents
        ):
            return True
        return any(
            (
                excluding_workload_checkpoint_id is None
                or intent.checkpoint_id != excluding_workload_checkpoint_id
            )
            and digest in intent.blob_sha256s
            for intent in workload_intents
        )

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
            if self._read_retirement(manifest.checkpoint_id) is not None:
                raise RunCheckpointConflict(
                    "checkpoint identity is retired and cannot be reused: "
                    f"{manifest.checkpoint_id}"
                )
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

    def assess_gc(
        self,
        checkpoint_id: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> CheckpointGcAssessment:
        with InterprocessFileLock(
            self._manifest_lock_path(checkpoint_id)
        ):
            retirement = self._read_retirement(checkpoint_id)
            if retirement is None:
                persistence_state, state_digest, blobs = (
                    self._current_gc_state_unlocked(checkpoint_id)
                )
            else:
                persistence_state = CheckpointPersistenceState(
                    str(retirement["persistence_state"])
                )
                state_digest = str(retirement["state_digest"])
                blobs = tuple(str(value) for value in retirement["blob_sha256s"])
            return CheckpointGcAssessment(
                namespace=CheckpointNamespace.RUN,
                checkpoint_id=checkpoint_id,
                persistence_state=persistence_state,
                state_digest=state_digest,
                blob_sha256s=blobs,
                closures=closures,
            )

    @staticmethod
    def _require_gc(
        checkpoint_id: str,
        gc: CheckpointGcAssessment,
    ) -> CheckpointGcAssessment:
        if type(gc) is not CheckpointGcAssessment:
            raise RuntimeError(
                "checkpoint physical GC requires a typed GC assessment"
            )
        if (
            gc.namespace is not CheckpointNamespace.RUN
            or gc.checkpoint_id != checkpoint_id
        ):
            raise RuntimeError(
                "checkpoint GC assessment does not bind the requested identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "checkpoint physical GC requires complete execution, evidence, "
                "and recovery closure with zero retained references"
            )
        return gc

    def purge(
        self,
        checkpoint_id: str,
        *,
        gc: CheckpointGcAssessment,
    ) -> bool:
        gc = self._require_gc(checkpoint_id, gc)
        manifest_path = self._manifest_path(checkpoint_id)

        with InterprocessFileLock(
            self._manifest_lock_path(checkpoint_id)
        ):
            retirement = self._read_retirement(checkpoint_id)
            if retirement is None:
                persistence_state, state_digest, blobs = (
                    self._current_gc_state_unlocked(checkpoint_id)
                )
                if (
                    persistence_state is not gc.persistence_state
                    or state_digest != gc.state_digest
                    or blobs != gc.blob_sha256s
                ):
                    raise RuntimeError(
                        "checkpoint GC assessment is stale for current durable state"
                    )
                self._write_retirement(gc, purged=False)
                retirement = self._read_retirement(checkpoint_id)
                if retirement is None:
                    raise RunCheckpointIntegrityError(
                        "checkpoint retirement publication disappeared"
                    )
            else:
                if (
                    str(retirement["persistence_state"])
                    != gc.persistence_state.value
                    or str(retirement["state_digest"]) != gc.state_digest
                    or tuple(str(v) for v in retirement["blob_sha256s"])
                    != gc.blob_sha256s
                ):
                    raise RuntimeError(
                        "checkpoint retirement generation changed across retry"
                    )
                if str(retirement["gc_proof_digest"]) != gc.proof_digest:
                    raise RuntimeError(
                        "checkpoint GC proof changed across retirement retry"
                    )
                if bool(retirement["purged"]):
                    return True

                # A crash may have published retirement before removing the live
                # manifest/intent. Any reappearing state must still be the exact
                # generation authorized by the tombstone.
                try:
                    current = self._current_gc_state_unlocked(checkpoint_id)
                except FileNotFoundError:
                    current = None
                if current is not None and (
                    current[0] is not gc.persistence_state
                    or current[1] != gc.state_digest
                    or current[2] != gc.blob_sha256s
                ):
                    raise RunCheckpointIntegrityError(
                        "retired checkpoint live state reappeared with another generation"
                    )

            if manifest_path.exists():
                durable_unlink(manifest_path)

            try:
                pending = self._intents.load(checkpoint_id)
            except CheckpointPublicationIntentCorruptionError as exc:
                raise RunCheckpointIntegrityError(
                    "retired checkpoint intent is corrupt"
                ) from exc
            if pending is not None:
                durable_unlink(self._intents._path(checkpoint_id))

            for digest in gc.blob_sha256s:
                with InterprocessFileLock(self._blob_lock_path(digest)):
                    if self._blob_referenced_elsewhere(
                        digest,
                        excluding_run_checkpoint_id=checkpoint_id,
                    ):
                        continue
                    blob_path = self._blob_path(digest)
                    if blob_path.exists():
                        durable_unlink(blob_path)

            self._write_retirement(gc, purged=True)
            return True


__all__ = ["DirectoryRunCheckpointStore"]
