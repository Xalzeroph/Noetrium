from __future__ import annotations

from contextlib import ExitStack
import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    atomic_replace_bytes,
    durable_unlink,
)

from ..api import (
    CheckpointGcAssessment,
    CheckpointNamespace,
    CheckpointPersistenceState,
    RunCheckpointConflict,
    RunCheckpointIntegrityError,
    RunCheckpointRecoveryRequired,
    WorkloadCheckpointBundle,
    WorkloadCheckpointManifest,
    WorkloadCheckpointPayload,
    WorkloadCheckpointStore,
)
from .directory_store import DirectoryRunCheckpointStore
from .publication_intent import (
    CheckpointPublicationIntent,
    CheckpointPublicationIntentConflict,
    CheckpointPublicationIntentCorruptionError,
    DirectoryCheckpointPublicationIntentStore,
)
from .retirement import CheckpointRetirementStore
from .workload_codec import WorkloadCheckpointManifestCodec


class DirectoryWorkloadCheckpointStore(WorkloadCheckpointStore):
    """Crash-durable workload checkpoint authority over the shared checkpoint CAS."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        root = Path(root)
        self._content = DirectoryRunCheckpointStore(root)
        self._manifests = root / "workload_manifests"
        self._manifest_locks = root / "workload_manifest_locks"
        self._manifests.mkdir(parents=True, exist_ok=True)
        self._manifest_locks.mkdir(parents=True, exist_ok=True)
        self._codec = WorkloadCheckpointManifestCodec()
        self._intents = DirectoryCheckpointPublicationIntentStore(
            root,
            namespace=CheckpointNamespace.WORKLOAD.value,
        )
        self._retirements = CheckpointRetirementStore(
            root,
            namespace=CheckpointNamespace.WORKLOAD,
        )

    @staticmethod
    def _sha(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _manifest_path(self, checkpoint_id: str) -> Path:
        safe = self._sha(checkpoint_id.encode("utf-8"))
        return self._manifests / f"{safe}.json"

    def _manifest_lock_path(self, checkpoint_id: str) -> Path:
        safe = self._sha(checkpoint_id.encode("utf-8"))
        return self._manifest_locks / f"{safe}.lock"

    def _publication_intent(
        self,
        manifest: WorkloadCheckpointManifest,
        encoded: bytes,
        payloads: tuple[WorkloadCheckpointPayload, ...],
    ) -> CheckpointPublicationIntent:
        return CheckpointPublicationIntent(
            namespace=CheckpointNamespace.WORKLOAD.value,
            checkpoint_id=manifest.checkpoint_id,
            manifest_sha256=self._intents.manifest_digest(encoded),
            blob_sha256s=tuple(
                sorted({item.ref.payload_sha256 for item in payloads})
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
                    "committed workload checkpoint has conflicting publication intent"
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
                "namespace": CheckpointNamespace.WORKLOAD.value,
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
                "pending workload checkpoint publication intent is corrupt"
            ) from exc

        if path.exists():
            encoded = path.read_bytes()
            manifest = self._codec.decode(encoded)
            if manifest.checkpoint_id != checkpoint_id:
                raise RunCheckpointIntegrityError(
                    "workload checkpoint manifest identity mismatch during GC assessment"
                )
            blobs = tuple(
                sorted({ref.payload_sha256 for ref in manifest.component_refs})
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
                        "committed workload checkpoint conflicts with pending "
                        "publication intent"
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
            f"workload checkpoint persistence state not found: {checkpoint_id}"
        )

    @staticmethod
    def _require_gc(
        checkpoint_id: str,
        gc: CheckpointGcAssessment,
    ) -> CheckpointGcAssessment:
        if type(gc) is not CheckpointGcAssessment:
            raise RuntimeError(
                "workload checkpoint physical GC requires a typed GC assessment"
            )
        if (
            gc.namespace is not CheckpointNamespace.WORKLOAD
            or gc.checkpoint_id != checkpoint_id
        ):
            raise RuntimeError(
                "workload checkpoint GC assessment does not bind the requested "
                "namespace and identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "workload checkpoint physical GC requires complete execution, "
                "evidence, and recovery closure with zero retained references"
            )
        return gc

    def publish(
        self,
        manifest: WorkloadCheckpointManifest,
        payloads: tuple[WorkloadCheckpointPayload, ...],
    ) -> WorkloadCheckpointManifest:
        try:
            WorkloadCheckpointBundle(manifest, payloads)
        except (TypeError, ValueError) as exc:
            raise RunCheckpointIntegrityError(
                "workload checkpoint payload refs do not match manifest"
            ) from exc
        path = self._manifest_path(manifest.checkpoint_id)
        encoded = self._codec.encode(manifest)
        intent = self._publication_intent(manifest, encoded, payloads)
        with InterprocessFileLock(
            self._manifest_lock_path(manifest.checkpoint_id)
        ):
            if self._retirements.load(manifest.checkpoint_id) is not None:
                raise RunCheckpointConflict(
                    "workload checkpoint identity is retired and cannot be reused: "
                    f"{manifest.checkpoint_id}"
                )
            if path.exists():
                current = self._codec.decode(path.read_bytes())
                if current != manifest:
                    raise RunCheckpointConflict(
                        "workload checkpoint id is already bound to different state: "
                        f"{manifest.checkpoint_id}"
                    )
                self._clear_intent(intent, manifest_committed=True)
                return current

            digests = tuple(
                sorted({item.ref.payload_sha256 for item in payloads})
            )
            with ExitStack() as blob_locks:
                for digest in digests:
                    blob_locks.enter_context(
                        InterprocessFileLock(
                            self._content._blob_lock_path(digest)
                        )
                    )
                # The blob locks fence GC across intent -> CAS -> manifest ->
                # intent-clear, eliminating the no-intent/no-manifest window.
                self._publish_intent(intent)
                for item in payloads:
                    self._content._write_blob_under_lock(
                        item.payload,
                        item.ref.payload_sha256,
                    )
                atomic_replace_bytes(path, encoded)
                self._clear_intent(intent, manifest_committed=True)
                return manifest

    def load(self, checkpoint_id: str) -> WorkloadCheckpointBundle:
        path = self._manifest_path(checkpoint_id)
        try:
            pending = self._intents.load(checkpoint_id)
        except CheckpointPublicationIntentCorruptionError as exc:
            raise RunCheckpointIntegrityError(
                "pending workload checkpoint publication intent is corrupt"
            ) from exc
        if not path.exists():
            if pending is not None:
                raise RunCheckpointRecoveryRequired(
                    checkpoint_id,
                    namespace=pending.namespace,
                    manifest_sha256=pending.manifest_sha256,
                    blob_sha256s=pending.blob_sha256s,
                )
            raise FileNotFoundError(
                f"workload checkpoint not found: {checkpoint_id}"
            )

        encoded = path.read_bytes()
        manifest = self._codec.decode(encoded)
        if manifest.checkpoint_id != checkpoint_id:
            raise RunCheckpointIntegrityError(
                "workload checkpoint lookup identity mismatch"
            )
        if pending is not None:
            expected = CheckpointPublicationIntent(
                namespace=self._intents.namespace,
                checkpoint_id=checkpoint_id,
                manifest_sha256=self._sha(encoded),
                blob_sha256s=tuple(
                    sorted(
                        {
                            ref.payload_sha256
                            for ref in manifest.component_refs
                        }
                    )
                ),
            )
            if pending != expected:
                raise RunCheckpointIntegrityError(
                    "committed workload checkpoint conflicts with pending "
                    "publication intent"
                )

        payloads: list[WorkloadCheckpointPayload] = []
        for ref in manifest.component_refs:
            payload_path = self._content._blob_path(ref.payload_sha256)
            try:
                payload = payload_path.read_bytes()
            except OSError as exc:
                raise RunCheckpointIntegrityError(
                    f"workload checkpoint component blob is missing: "
                    f"{ref.component_id}"
                ) from exc
            if self._sha(payload) != ref.payload_sha256:
                raise RunCheckpointIntegrityError(
                    f"workload checkpoint component checksum mismatch: "
                    f"{ref.component_id}"
                )
            try:
                payloads.append(WorkloadCheckpointPayload(ref, payload))
            except ValueError as exc:
                raise RunCheckpointIntegrityError(
                    f"workload checkpoint component payload does not match "
                    f"manifest: {ref.component_id}"
                ) from exc
        return WorkloadCheckpointBundle(manifest, tuple(payloads))

    def assess_gc(
        self,
        checkpoint_id: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> CheckpointGcAssessment:
        with InterprocessFileLock(
            self._manifest_lock_path(checkpoint_id)
        ):
            retirement = self._retirements.load(checkpoint_id)
            if retirement is None:
                persistence_state, state_digest, blobs = (
                    self._current_gc_state_unlocked(checkpoint_id)
                )
            else:
                persistence_state = retirement.persistence_state
                state_digest = retirement.state_digest
                blobs = retirement.blob_sha256s
            return CheckpointGcAssessment(
                namespace=CheckpointNamespace.WORKLOAD,
                checkpoint_id=checkpoint_id,
                persistence_state=persistence_state,
                state_digest=state_digest,
                blob_sha256s=blobs,
                closures=closures,
            )

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
            retirement = self._retirements.load(checkpoint_id)
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
                        "workload checkpoint GC assessment is stale for current "
                        "durable state"
                    )
                retirement = self._retirements.publish(gc, purged=False)
            else:
                if not retirement.binds(gc):
                    raise RuntimeError(
                        "workload checkpoint retirement generation or GC proof "
                        "changed across retry"
                    )
                if retirement.purged:
                    return True
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
                        "retired workload checkpoint live state reappeared with "
                        "another generation"
                    )

            if manifest_path.exists():
                durable_unlink(manifest_path)

            try:
                pending = self._intents.load(checkpoint_id)
            except CheckpointPublicationIntentCorruptionError as exc:
                raise RunCheckpointIntegrityError(
                    "retired workload checkpoint intent is corrupt"
                ) from exc
            if pending is not None:
                durable_unlink(self._intents._path(checkpoint_id))

            for digest in gc.blob_sha256s:
                with InterprocessFileLock(
                    self._content._blob_lock_path(digest)
                ):
                    if self._content._blob_referenced_elsewhere(
                        digest,
                        excluding_workload_checkpoint_id=checkpoint_id,
                    ):
                        continue
                    blob_path = self._content._blob_path(digest)
                    if blob_path.exists():
                        durable_unlink(blob_path)

            self._retirements.publish(gc, purged=True)
            return True


__all__ = ["DirectoryWorkloadCheckpointStore"]
