from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability import InterprocessFileLock
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from ..api import (
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
from .workload_codec import WorkloadCheckpointManifestCodec


class DirectoryWorkloadCheckpointStore(WorkloadCheckpointStore):
    """Crash-durable content-addressed storage for workload checkpoints.

    Blob writing and checksum behavior are delegated to the existing checkpoint
    content authority.  This class adds only the workload manifest namespace;
    it does not create a second blob format or persistence protocol.
    """

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self._content = DirectoryRunCheckpointStore(Path(root))
        self._manifests = Path(root) / "workload_manifests"
        self._manifest_locks = Path(root) / "workload_manifest_locks"
        self._manifests.mkdir(parents=True, exist_ok=True)
        self._manifest_locks.mkdir(parents=True, exist_ok=True)
        self._codec = WorkloadCheckpointManifestCodec()
        self._intents = DirectoryCheckpointPublicationIntentStore(
            Path(root),
            namespace="workload",
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
            namespace="workload",
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
            if path.exists():
                current = self._codec.decode(path.read_bytes())
                if current != manifest:
                    raise RunCheckpointConflict(
                        "workload checkpoint id is already bound to different state: "
                        f"{manifest.checkpoint_id}"
                    )
                self._clear_intent(intent, manifest_committed=True)
                return current

            self._publish_intent(intent)
            for item in payloads:
                self._content._write_blob(
                    item.payload,
                    item.ref.payload_sha256,
                )
            atomic_replace_bytes(path, encoded)
            self._clear_intent(intent, manifest_committed=True)
            return manifest

    def load(self, checkpoint_id: str) -> WorkloadCheckpointBundle:
        path = self._manifest_path(checkpoint_id)
        if not path.exists():
            try:
                pending = self._intents.load(checkpoint_id)
            except CheckpointPublicationIntentCorruptionError as exc:
                raise RunCheckpointIntegrityError(
                    "pending workload checkpoint publication intent is corrupt"
                ) from exc
            if pending is not None:
                raise RunCheckpointRecoveryRequired(
                    checkpoint_id,
                    namespace=pending.namespace,
                    manifest_sha256=pending.manifest_sha256,
                    blob_sha256s=pending.blob_sha256s,
                )
            raise FileNotFoundError(f"workload checkpoint not found: {checkpoint_id}")
        manifest = self._codec.decode(path.read_bytes())
        if manifest.checkpoint_id != checkpoint_id:
            raise RunCheckpointIntegrityError("workload checkpoint lookup identity mismatch")
        payloads: list[WorkloadCheckpointPayload] = []
        for ref in manifest.component_refs:
            payload_path = self._content._blob_path(ref.payload_sha256)
            payload = payload_path.read_bytes()
            if self._sha(payload) != ref.payload_sha256:
                raise RunCheckpointIntegrityError(
                    f"workload checkpoint component checksum mismatch: {ref.component_id}"
                )
            payloads.append(WorkloadCheckpointPayload(ref, payload))
        return WorkloadCheckpointBundle(manifest, tuple(payloads))


__all__ = ["DirectoryWorkloadCheckpointStore"]
