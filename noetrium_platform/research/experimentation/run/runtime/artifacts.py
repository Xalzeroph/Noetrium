from __future__ import annotations

import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_bytes, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes, durable_append_bytes

from .diagnostics import json_default
from ..api.artifacts import (
    RunArtifactFinalizationError,
    RunArtifactKind,
    RunArtifactSealedError,
    RunArtifactSnapshotReceipt,
    RunArtifactStorePort,
    RunArtifactVerificationError,
    RunArtifactWriteActorPort,
)

_FINALIZED_DIR = ".run-artifact-finalized"
_RECEIPT_FIELDS = frozenset({
    "run_id", "artifact_ref", "artifact_kind", "generation",
    "content_sha256", "byte_size", "record_count",
})


class DirectoryRunArtifactStore(RunArtifactStorePort):
    """Crash-safe run-local artifact authority with durable logical seals."""

    def __init__(
        self,
        root: Path | str,
        *,
        run_id: str,
        writer_actor: RunArtifactWriteActorPort,
    ) -> None:
        if type(run_id) is not str or not run_id.strip() or "/" in run_id or "\\" in run_id:
            raise ValueError("run artifact store run_id must be a non-empty identity")
        self.root = Path(root).expanduser().resolve()
        self.run_id = run_id
        self._writer_actor = writer_actor

    def _resolve_ref(self, name: str, *, create_parent: bool) -> Path:
        if type(name) is not str or not name.strip() or "\\" in name or Path(name).is_absolute():
            raise ValueError("run artifact name must be a non-empty run-local path")
        parts = name.split("/")
        if any(not part or part in {".", ".."} for part in parts):
            raise ValueError("run artifact name contains an unsafe path component")
        if parts[0] == _FINALIZED_DIR:
            raise ValueError("run artifact name uses a reserved authority path")
        target = (self.root / Path(*parts)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("run artifact path escapes the run root") from exc
        if create_parent:
            target.parent.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _seal_key(artifact_ref: str) -> str:
        return hashlib.sha256(artifact_ref.encode("utf-8")).hexdigest()

    def _seal_path(self, artifact_ref: str) -> Path:
        return self.root / _FINALIZED_DIR / "seals" / f"{self._seal_key(artifact_ref)}.json"

    def _ledger_path(self, generation: str) -> Path:
        return self.root / _FINALIZED_DIR / "generations" / f"{generation}.json"

    def _require_unsealed(self, artifact_ref: str) -> None:
        seal = self._seal_path(artifact_ref)
        try:
            seal.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RunArtifactSealedError(
                f"run artifact seal state cannot be inspected: {artifact_ref}"
            ) from exc
        raise RunArtifactSealedError(f"run artifact is finalized and sealed: {artifact_ref}")

    def path(self, name: str, *, kind: RunArtifactKind) -> str:
        if type(kind) is not RunArtifactKind:
            raise ValueError("run artifact kind must be RunArtifactKind")
        return str(self._resolve_ref(name, create_parent=True))

    def directory(self, name: str, *, kind: RunArtifactKind) -> str:
        if type(kind) is not RunArtifactKind:
            raise ValueError("run artifact kind must be RunArtifactKind")
        target = self._resolve_ref(name, create_parent=False)
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def publish_json(self, name: str, payload: JsonValue, *, kind: RunArtifactKind) -> str:
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n"
        return self.publish_text(name, body, kind=kind)

    def publish_text(self, name: str, content: str, *, kind: RunArtifactKind) -> str:
        target = self._resolve_ref(name, create_parent=True)

        def publish_owned() -> str:
            self._require_unsealed(name)
            atomic_replace_bytes(target, content.encode("utf-8"))
            return str(target)

        return self._writer_actor.call(f"publish:{name}", publish_owned)

    def append_json(
        self,
        name: str,
        payload: JsonObject,
        *,
        kind: RunArtifactKind,
    ) -> str:
        target = self._resolve_ref(name, create_parent=True)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=json_default) + "\n"

        def append_owned() -> str:
            self._require_unsealed(name)
            durable_append_bytes(target, encoded.encode("utf-8"))
            return str(target)

        return self._writer_actor.call(f"append:{name}", append_owned)

    def _snapshot_unlocked(
        self,
        artifact_ref: str,
        *,
        kind: RunArtifactKind,
        record_stream: bool,
        error_type: type[RuntimeError],
    ) -> RunArtifactSnapshotReceipt:
        if type(kind) is not RunArtifactKind:
            raise error_type("run artifact snapshot kind is invalid")
        if type(record_stream) is not bool:
            raise error_type("run artifact record_stream flag must be boolean")
        target = self._resolve_ref(artifact_ref, create_parent=False)
        if not target.is_file():
            raise error_type(f"run artifact is missing or not a regular file: {artifact_ref}")
        before = target.stat()
        hasher = hashlib.sha256()
        byte_size = 0
        record_count = 0 if record_stream else None
        try:
            with target.open("rb") as handle:
                if record_stream:
                    for line in handle:
                        hasher.update(line)
                        byte_size += len(line)
                        assert record_count is not None
                        record_count += 1
                else:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                        byte_size += len(chunk)
        except OSError as exc:
            raise error_type(f"run artifact cannot be read: {artifact_ref}") from exc
        after = target.stat()
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if before_identity != after_identity or after.st_size != byte_size:
            raise error_type(f"run artifact changed during snapshot: {artifact_ref}")
        content_sha256 = hasher.hexdigest()
        generation = canonical_digest({
            "schema_version": "1",
            "run_id": self.run_id,
            "artifact_ref": artifact_ref,
            "artifact_kind": kind.value,
            "content_sha256": content_sha256,
            "byte_size": byte_size,
            "record_count": record_count,
        })
        return RunArtifactSnapshotReceipt(
            run_id=self.run_id,
            artifact_ref=artifact_ref,
            artifact_kind=kind,
            generation=generation,
            content_sha256=content_sha256,
            byte_size=byte_size,
            record_count=record_count,
        )

    @staticmethod
    def _decode_receipt(raw: bytes, *, error_type: type[RuntimeError]) -> RunArtifactSnapshotReceipt:
        try:
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict) or set(document) != _RECEIPT_FIELDS:
                raise ValueError("receipt fields are not exact")
            record_count = document["record_count"]
            if record_count is not None and type(record_count) is not int:
                raise TypeError("record_count must be integer or null")
            if type(document["byte_size"]) is not int:
                raise TypeError("byte_size must be integer")
            strings = {
                field: document[field]
                for field in ("run_id", "artifact_ref", "artifact_kind", "generation", "content_sha256")
            }
            if any(type(value) is not str for value in strings.values()):
                raise TypeError("receipt string fields must be strings")
            return RunArtifactSnapshotReceipt(
                run_id=strings["run_id"],
                artifact_ref=strings["artifact_ref"],
                artifact_kind=RunArtifactKind(strings["artifact_kind"]),
                generation=strings["generation"],
                content_sha256=strings["content_sha256"],
                byte_size=document["byte_size"],
                record_count=record_count,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise error_type("run artifact finalized receipt is corrupt") from exc

    @staticmethod
    def _read_bytes(path: Path, *, error_type: type[RuntimeError], label: str) -> bytes:
        try:
            if not path.is_file():
                raise error_type(f"run artifact {label} is missing")
            return path.read_bytes()
        except OSError as exc:
            raise error_type(f"run artifact {label} cannot be read") from exc

    def _verify_finalized_unlocked(
        self,
        receipt: RunArtifactSnapshotReceipt,
    ) -> RunArtifactSnapshotReceipt:
        expected = canonical_bytes(receipt, indent=2) + b"\n"
        seal = self._seal_path(receipt.artifact_ref)
        if self._read_bytes(seal, error_type=RunArtifactVerificationError, label="seal") != expected:
            raise RunArtifactVerificationError("run artifact seal does not match receipt")
        ledger = self._ledger_path(receipt.generation)
        if ledger.exists():
            if self._read_bytes(
                ledger,
                error_type=RunArtifactVerificationError,
                label="generation ledger",
            ) != expected:
                raise RunArtifactVerificationError("run artifact generation ledger does not match receipt")
        current = self._snapshot_unlocked(
            receipt.artifact_ref,
            kind=receipt.artifact_kind,
            record_stream=receipt.record_count is not None,
            error_type=RunArtifactVerificationError,
        )
        if current != receipt:
            raise RunArtifactVerificationError("run artifact content drifted after finalization")
        return receipt

    def _ensure_generation_index(self, receipt: RunArtifactSnapshotReceipt) -> None:
        payload = canonical_bytes(receipt, indent=2) + b"\n"
        ledger = self._ledger_path(receipt.generation)
        if ledger.exists():
            recorded = self._read_bytes(
                ledger,
                error_type=RunArtifactFinalizationError,
                label="generation ledger",
            )
            if recorded == payload:
                return
        atomic_replace_bytes(ledger, payload)

    def finalize(
        self,
        artifact_ref: str,
        *,
        kind: RunArtifactKind,
        record_stream: bool,
    ) -> RunArtifactSnapshotReceipt:
        def finalize_owned() -> RunArtifactSnapshotReceipt:
            seal = self._seal_path(artifact_ref)
            if seal.exists():
                recorded = self._decode_receipt(
                    self._read_bytes(seal, error_type=RunArtifactFinalizationError, label="seal"),
                    error_type=RunArtifactFinalizationError,
                )
                if recorded.artifact_kind is not kind or (recorded.record_count is not None) is not record_stream:
                    raise RunArtifactFinalizationError("run artifact is already sealed with different semantics")
                self._ensure_generation_index(recorded)
                try:
                    return self._verify_finalized_unlocked(recorded)
                except RunArtifactVerificationError as exc:
                    raise RunArtifactFinalizationError("sealed run artifact no longer matches its receipt") from exc

            receipt = self._snapshot_unlocked(
                artifact_ref,
                kind=kind,
                record_stream=record_stream,
                error_type=RunArtifactFinalizationError,
            )
            payload = canonical_bytes(receipt, indent=2) + b"\n"
            atomic_replace_bytes(seal, payload)
            try:
                verified = self._verify_finalized_unlocked(receipt)
            except RunArtifactVerificationError as exc:
                raise RunArtifactFinalizationError("finalized run artifact failed immediate verification") from exc
            self._ensure_generation_index(receipt)
            return verified

        return self._writer_actor.call(f"finalize:{artifact_ref}", finalize_owned)

    def verify_finalized(self, receipt: RunArtifactSnapshotReceipt) -> RunArtifactSnapshotReceipt:
        if type(receipt) is not RunArtifactSnapshotReceipt:
            raise RunArtifactVerificationError("run artifact verification requires a typed snapshot receipt")
        if receipt.run_id != self.run_id:
            raise RunArtifactVerificationError("run artifact snapshot belongs to a different run")
        return self._writer_actor.call(
            f"verify-finalized:{receipt.artifact_ref}",
            self._verify_finalized_unlocked,
            receipt,
        )


__all__ = ["DirectoryRunArtifactStore"]
