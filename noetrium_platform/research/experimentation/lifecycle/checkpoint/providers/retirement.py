from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)

from ..api import (
    CheckpointGcAssessment,
    CheckpointNamespace,
    CheckpointPersistenceState,
    RunCheckpointIntegrityError,
)


_SCHEMA = "noetrium.checkpoint-retirement.v1"
_FIELDS = {
    "namespace",
    "checkpoint_id",
    "persistence_state",
    "state_digest",
    "blob_sha256s",
    "gc_proof_digest",
    "purged",
}
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class CheckpointRetirementRecord:
    namespace: CheckpointNamespace
    checkpoint_id: str
    persistence_state: CheckpointPersistenceState
    state_digest: str
    blob_sha256s: tuple[str, ...]
    gc_proof_digest: str
    purged: bool

    @classmethod
    def from_gc(
        cls,
        gc: CheckpointGcAssessment,
        *,
        purged: bool,
    ) -> "CheckpointRetirementRecord":
        return cls(
            namespace=gc.namespace,
            checkpoint_id=gc.checkpoint_id,
            persistence_state=gc.persistence_state,
            state_digest=gc.state_digest,
            blob_sha256s=gc.blob_sha256s,
            gc_proof_digest=gc.proof_digest,
            purged=purged,
        )

    def __post_init__(self) -> None:
        if type(self.namespace) is not CheckpointNamespace:
            raise TypeError("checkpoint retirement namespace must be typed")
        if (
            type(self.checkpoint_id) is not str
            or not self.checkpoint_id.strip()
            or self.checkpoint_id != self.checkpoint_id.strip()
        ):
            raise ValueError("checkpoint retirement checkpoint_id must be canonical")
        if type(self.persistence_state) is not CheckpointPersistenceState:
            raise TypeError(
                "checkpoint retirement persistence_state must be typed"
            )
        for label, value in (
            ("state_digest", self.state_digest),
            ("gc_proof_digest", self.gc_proof_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in _HEX for ch in value)
            ):
                raise ValueError(
                    f"checkpoint retirement {label} must be lowercase sha256"
                )
        if type(self.blob_sha256s) is not tuple or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in _HEX for ch in value)
            for value in self.blob_sha256s
        ):
            raise TypeError(
                "checkpoint retirement blob_sha256s must be sha256 tuple"
            )
        if self.blob_sha256s != tuple(sorted(set(self.blob_sha256s))):
            raise ValueError(
                "checkpoint retirement blob_sha256s must be unique sorted order"
            )
        if type(self.purged) is not bool:
            raise TypeError("checkpoint retirement purged must be bool")

    def binds(self, gc: CheckpointGcAssessment) -> bool:
        return (
            gc.namespace is self.namespace
            and gc.checkpoint_id == self.checkpoint_id
            and gc.persistence_state is self.persistence_state
            and gc.state_digest == self.state_digest
            and gc.blob_sha256s == self.blob_sha256s
            and gc.proof_digest == self.gc_proof_digest
        )

    def document(self) -> dict[str, object]:
        return {
            "namespace": self.namespace.value,
            "checkpoint_id": self.checkpoint_id,
            "persistence_state": self.persistence_state.value,
            "state_digest": self.state_digest,
            "blob_sha256s": list(self.blob_sha256s),
            "gc_proof_digest": self.gc_proof_digest,
            "purged": self.purged,
        }


class CheckpointRetirementStore:
    """Durable terminal checkpoint identity and GC-proof authority."""

    def __init__(self, root: Path, *, namespace: CheckpointNamespace) -> None:
        if type(namespace) is not CheckpointNamespace:
            raise TypeError("checkpoint retirement namespace must be typed")
        self.namespace = namespace
        self.root = Path(root) / "retirement" / namespace.value
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, checkpoint_id: str) -> Path:
        safe = hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest()
        return self.root / f"{safe}.json"

    def load(
        self,
        checkpoint_id: str,
    ) -> CheckpointRetirementRecord | None:
        path = self._path(checkpoint_id)
        if not path.exists():
            return None
        try:
            payload = decode_checksummed_document(
                path.read_bytes(),
                expected_schema=_SCHEMA,
            ).payload
            if set(payload) != _FIELDS:
                raise ValueError("checkpoint retirement fields drifted")
            namespace = CheckpointNamespace(str(payload["namespace"]))
            persistence_state = CheckpointPersistenceState(
                str(payload["persistence_state"])
            )
            blobs_raw = payload["blob_sha256s"]
            if not isinstance(blobs_raw, list):
                raise TypeError("checkpoint retirement blobs must be a list")
            record = CheckpointRetirementRecord(
                namespace=namespace,
                checkpoint_id=str(payload["checkpoint_id"]),
                persistence_state=persistence_state,
                state_digest=str(payload["state_digest"]),
                blob_sha256s=tuple(str(value) for value in blobs_raw),
                gc_proof_digest=str(payload["gc_proof_digest"]),
                purged=payload["purged"],
            )
            expected_name = hashlib.sha256(
                record.checkpoint_id.encode("utf-8")
            ).hexdigest() + ".json"
            if record.namespace is not self.namespace:
                raise ValueError("checkpoint retirement namespace drifted")
            if record.checkpoint_id != checkpoint_id:
                raise ValueError("checkpoint retirement identity drifted")
            if path.name != expected_name:
                raise ValueError("checkpoint retirement filename identity drifted")
            return record
        except (
            ChecksummedDocumentError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            raise RunCheckpointIntegrityError(
                f"checkpoint retirement document is corrupt: "
                f"{self.namespace.value}:{checkpoint_id}"
            ) from exc

    def publish(
        self,
        gc: CheckpointGcAssessment,
        *,
        purged: bool,
    ) -> CheckpointRetirementRecord:
        if gc.namespace is not self.namespace:
            raise RuntimeError(
                "checkpoint retirement GC assessment namespace drifted"
            )
        proposed = CheckpointRetirementRecord.from_gc(gc, purged=purged)
        current = self.load(gc.checkpoint_id)
        if current is not None:
            if not current.binds(gc):
                raise RuntimeError(
                    "checkpoint retirement generation or GC proof changed across retry"
                )
            if current.purged:
                return current
            if not purged:
                return current
        atomic_replace_bytes(
            self._path(gc.checkpoint_id),
            encode_checksummed_document(_SCHEMA, proposed.document()),
        )
        return proposed


__all__ = [
    "CheckpointRetirementRecord",
    "CheckpointRetirementStore",
]
