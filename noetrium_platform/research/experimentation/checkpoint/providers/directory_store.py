from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint
from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes, sha256_file

from .codec import RunCheckpointManifestCodec
from ..api.contracts import (
    RunCheckpointBundle,
    RunCheckpointConflict,
    RunCheckpointIntegrityError,
    RunCheckpointManifest,
    RunCheckpointStore,
    RunParticipantPayload,
)


class DirectoryRunCheckpointStore(RunCheckpointStore):
    """Crash-durable content-addressed persistence for generic participant checkpoints."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.manifests = self.root / "manifests"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        self.codec = RunCheckpointManifestCodec()

    @staticmethod
    def _sha(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / f"{digest}.bin"

    def _manifest_path(self, checkpoint_id: str) -> Path:
        safe = hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest()
        return self.manifests / f"{safe}.json"

    def _write_blob(self, payload: bytes, expected_digest: str) -> None:
        actual = self._sha(payload)
        if actual != expected_digest:
            raise RunCheckpointIntegrityError(
                f"checkpoint payload digest mismatch: expected={expected_digest} actual={actual}"
            )
        path = self._blob_path(actual)
        if path.exists():
            stored_digest, stored_size = sha256_file(path)
            if stored_digest != actual or stored_size != len(payload):
                raise RunCheckpointIntegrityError(f"corrupt existing checkpoint blob: {actual}")
            return
        atomic_replace_bytes(path, payload)

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
        for item in participant_payloads:
            self._write_blob(item.checkpoint.opaque_payload, item.checkpoint.ref.payload_sha256)

        path = self._manifest_path(manifest.checkpoint_id)
        encoded = self.codec.encode(manifest)
        if path.exists():
            current = self.codec.decode(path.read_bytes())
            if current != manifest:
                raise RunCheckpointConflict(
                    f"checkpoint id is already bound to different state: {manifest.checkpoint_id}"
                )
            return current
        atomic_replace_bytes(path, encoded)
        return manifest

    def load(self, checkpoint_id: str) -> RunCheckpointBundle:
        path = self._manifest_path(checkpoint_id)
        if not path.exists():
            raise FileNotFoundError(f"study checkpoint not found: {checkpoint_id}")
        manifest = self.codec.decode(path.read_bytes())
        if manifest.checkpoint_id != checkpoint_id:
            raise RunCheckpointIntegrityError("checkpoint lookup identity mismatch")
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
