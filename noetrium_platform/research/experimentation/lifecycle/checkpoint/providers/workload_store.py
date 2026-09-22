from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from ..api import (
    RunCheckpointConflict,
    RunCheckpointIntegrityError,
    WorkloadCheckpointBundle,
    WorkloadCheckpointManifest,
    WorkloadCheckpointPayload,
    WorkloadCheckpointStore,
)
from .directory_store import DirectoryRunCheckpointStore
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
        self._manifests.mkdir(parents=True, exist_ok=True)
        self._codec = WorkloadCheckpointManifestCodec()

    @staticmethod
    def _sha(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _manifest_path(self, checkpoint_id: str) -> Path:
        safe = self._sha(checkpoint_id.encode("utf-8"))
        return self._manifests / f"{safe}.json"

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
        for item in payloads:
            self._content._write_blob(item.payload, item.ref.payload_sha256)
        path = self._manifest_path(manifest.checkpoint_id)
        encoded = self._codec.encode(manifest)
        if path.exists():
            current = self._codec.decode(path.read_bytes())
            if current != manifest:
                raise RunCheckpointConflict(
                    f"workload checkpoint id is already bound to different state: {manifest.checkpoint_id}"
                )
            return current
        atomic_replace_bytes(path, encoded)
        return manifest

    def load(self, checkpoint_id: str) -> WorkloadCheckpointBundle:
        path = self._manifest_path(checkpoint_id)
        if not path.exists():
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
