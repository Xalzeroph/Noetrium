from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_bytes, strict_json_loads
from noetrium_platform.foundation.kernel.kernel.durability import (
    atomic_replace_bytes,
    durable_unlink,
)


_HEX = frozenset("0123456789abcdef")
_SCHEMA = "noetrium.checkpoint-publication-intent.v1"
_FIELDS = {
    "schema",
    "namespace",
    "checkpoint_id",
    "manifest_sha256",
    "blob_sha256s",
}


class CheckpointPublicationIntentConflict(RuntimeError):
    pass


class CheckpointPublicationIntentCorruptionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CheckpointPublicationIntent:
    """Durable owner record for one not-yet-committed checkpoint publication."""

    namespace: str
    checkpoint_id: str
    manifest_sha256: str
    blob_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("namespace", self.namespace),
            ("checkpoint_id", self.checkpoint_id),
        ):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"checkpoint publication intent {label} must be canonical text"
                )
        if (
            type(self.manifest_sha256) is not str
            or len(self.manifest_sha256) != 64
            or any(char not in _HEX for char in self.manifest_sha256)
        ):
            raise ValueError(
                "checkpoint publication intent manifest_sha256 must be lowercase sha256"
            )
        if type(self.blob_sha256s) is not tuple or any(
            type(value) is not str
            or len(value) != 64
            or any(char not in _HEX for char in value)
            for value in self.blob_sha256s
        ):
            raise TypeError(
                "checkpoint publication intent blob_sha256s must be sha256 tuple"
            )
        if self.blob_sha256s != tuple(sorted(set(self.blob_sha256s))):
            raise ValueError(
                "checkpoint publication intent blob_sha256s must be unique sorted order"
            )

    def document(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "namespace": self.namespace,
            "checkpoint_id": self.checkpoint_id,
            "manifest_sha256": self.manifest_sha256,
            "blob_sha256s": list(self.blob_sha256s),
        }


class DirectoryCheckpointPublicationIntentStore:
    """Crash-durable exact-id publication intent authority.

    The caller must hold the checkpoint's manifest lock while mutating this
    store. An intent is published before any content blob and cleared only
    after the manifest is durably visible.
    """

    def __init__(self, root: Path, *, namespace: str) -> None:
        if (
            type(namespace) is not str
            or not namespace.strip()
            or namespace != namespace.strip()
        ):
            raise ValueError("checkpoint publication namespace must be canonical text")
        self.root = Path(root) / "publication_intents" / namespace
        self.namespace = namespace
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def manifest_digest(encoded_manifest: bytes) -> str:
        return hashlib.sha256(encoded_manifest).hexdigest()

    def _path(self, checkpoint_id: str) -> Path:
        safe = hashlib.sha256(checkpoint_id.encode("utf-8")).hexdigest()
        return self.root / f"{safe}.json"

    def load(self, checkpoint_id: str) -> CheckpointPublicationIntent | None:
        path = self._path(checkpoint_id)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            document = strict_json_loads(raw)
            if not isinstance(document, Mapping):
                raise TypeError("intent document must be an object")
            if set(document) != _FIELDS:
                raise ValueError("intent document schema fields drifted")
            if document.get("schema") != _SCHEMA:
                raise ValueError("unsupported publication intent schema")
            blob_values = document.get("blob_sha256s")
            if not isinstance(blob_values, list):
                raise TypeError("intent blob_sha256s must be a list")
            intent = CheckpointPublicationIntent(
                namespace=str(document["namespace"]),
                checkpoint_id=str(document["checkpoint_id"]),
                manifest_sha256=str(document["manifest_sha256"]),
                blob_sha256s=tuple(str(value) for value in blob_values),
            )
            if intent.namespace != self.namespace:
                raise ValueError("publication intent namespace drifted")
            if intent.checkpoint_id != checkpoint_id:
                raise ValueError("publication intent checkpoint identity drifted")
            if canonical_bytes(intent.document()) != raw:
                raise ValueError("publication intent is not canonical JSON")
            return intent
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, CheckpointPublicationIntentCorruptionError):
                raise
            raise CheckpointPublicationIntentCorruptionError(
                f"checkpoint publication intent is corrupt: {checkpoint_id}"
            ) from exc

    def publish(
        self,
        intent: CheckpointPublicationIntent,
    ) -> CheckpointPublicationIntent:
        if intent.namespace != self.namespace:
            raise ValueError("publication intent namespace does not match store")
        path = self._path(intent.checkpoint_id)
        current = self.load(intent.checkpoint_id)
        if current is not None:
            if current != intent:
                raise CheckpointPublicationIntentConflict(
                    "checkpoint publication intent already binds different content: "
                    f"{intent.checkpoint_id}"
                )
            return current
        atomic_replace_bytes(path, canonical_bytes(intent.document()))
        return intent

    def clear(self, expected: CheckpointPublicationIntent) -> None:
        current = self.load(expected.checkpoint_id)
        if current is None:
            return
        if current != expected:
            raise CheckpointPublicationIntentConflict(
                "checkpoint publication intent changed before clear: "
                f"{expected.checkpoint_id}"
            )
        durable_unlink(self._path(expected.checkpoint_id))


__all__ = [
    "CheckpointPublicationIntent",
    "CheckpointPublicationIntentConflict",
    "CheckpointPublicationIntentCorruptionError",
    "DirectoryCheckpointPublicationIntentStore",
]
