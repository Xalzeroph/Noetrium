from __future__ import annotations

import hashlib
import json
import shutil
from enum import StrEnum
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    JsonObject,
    JsonValue,
    canonical_bytes,
    canonical_digest,
    validate_durable_carrier_closures,
)
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    InterprocessFileLock,
    atomic_replace_bytes,
    decode_checksummed_document,
    durable_append_bytes,
    encode_checksummed_document,
    fsync_directory,
)

from ..api.artifacts import (
    RunArtifactFinalizationError,
    RunArtifactGcAssessment,
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
_RUN_ARTIFACT_RETIREMENT_SCHEMA = "run-artifact.retirement.v1"
_RUN_ARTIFACT_RETIREMENT_FIELDS = frozenset({
    "run_id", "root_name", "tree_digest", "entry_count", "total_bytes",
    "gc_proof_digest", "phase",
})


class _RunArtifactRetirementPhase(StrEnum):
    RETIRED = "retired"
    QUARANTINED = "quarantined"
    PURGED = "purged"



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
        key = hashlib.sha256(
            f"{self.run_id}:{self.root.name}".encode("utf-8")
        ).hexdigest()
        self._carrier_key = key
        self._process_lock_path = (
            self.root.parent
            / ".run-artifact-locks"
            / f"{key}.lock"
        )

    def _retirement_path(self) -> Path:
        return (
            self.root.parent
            / ".run-artifact-retired"
            / f"{self._carrier_key}.json"
        )

    def _quarantine_path(self) -> Path:
        return (
            self.root.parent
            / ".run-artifact-quarantine"
            / self._carrier_key
        )

    def _load_retirement(self) -> dict[str, object] | None:
        path = self._retirement_path()
        if not path.exists():
            return None
        try:
            payload = decode_checksummed_document(
                path.read_bytes(),
                expected_schema=_RUN_ARTIFACT_RETIREMENT_SCHEMA,
            ).payload
        except (OSError, ChecksummedDocumentError) as exc:
            raise RunArtifactVerificationError(
                "run artifact retirement intent is corrupt"
            ) from exc
        if set(payload) != _RUN_ARTIFACT_RETIREMENT_FIELDS:
            raise RunArtifactVerificationError(
                "run artifact retirement fields are not exact"
            )
        if (
            payload.get("run_id") != self.run_id
            or payload.get("root_name") != self.root.name
        ):
            raise RunArtifactVerificationError(
                "run artifact retirement identity mismatch"
            )
        try:
            tree_digest = str(payload["tree_digest"])
            proof_digest = str(payload["gc_proof_digest"])
            if (
                len(tree_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in tree_digest)
                or len(proof_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in proof_digest)
            ):
                raise ValueError("invalid retirement digest")
            entry_count = payload["entry_count"]
            total_bytes = payload["total_bytes"]
            if (
                type(entry_count) is not int
                or entry_count < 0
                or type(total_bytes) is not int
                or total_bytes < 0
            ):
                raise ValueError("invalid retirement counters")
            phase = _RunArtifactRetirementPhase(str(payload["phase"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RunArtifactVerificationError(
                "run artifact retirement intent is invalid"
            ) from exc
        return {
            "run_id": self.run_id,
            "root_name": self.root.name,
            "tree_digest": tree_digest,
            "entry_count": entry_count,
            "total_bytes": total_bytes,
            "gc_proof_digest": proof_digest,
            "phase": phase,
        }

    def _publish_retirement(
        self,
        gc: RunArtifactGcAssessment,
        phase: _RunArtifactRetirementPhase,
    ) -> None:
        atomic_replace_bytes(
            self._retirement_path(),
            encode_checksummed_document(
                _RUN_ARTIFACT_RETIREMENT_SCHEMA,
                {
                    "run_id": self.run_id,
                    "root_name": self.root.name,
                    "tree_digest": gc.tree_digest,
                    "entry_count": gc.entry_count,
                    "total_bytes": gc.total_bytes,
                    "gc_proof_digest": gc.proof_digest,
                    "phase": phase.value,
                },
            ),
        )

    def _require_active(self) -> None:
        if self._retirement_path().exists():
            raise RunArtifactSealedError(
                "run artifact carrier identity is retired"
            )

    def _tree_identity(self, root: Path) -> tuple[str, int, int]:
        if not root.exists():
            raise KeyError(f"run artifact carrier does not exist: {self.run_id}")
        if root.is_symlink() or not root.is_dir():
            raise RunArtifactVerificationError(
                "run artifact carrier root is not an owned directory"
            )
        entries: list[tuple[object, ...]] = []
        total_bytes = 0
        observed_kinds: list[tuple[str, str]] = []
        for candidate in sorted(
            root.rglob("*"),
            key=lambda value: value.relative_to(root).as_posix(),
        ):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise RunArtifactVerificationError(
                    f"run artifact carrier contains symlink: {relative}"
                )
            if candidate.is_dir():
                entries.append(("dir", relative))
                observed_kinds.append(("dir", relative))
                continue
            if not candidate.is_file():
                raise RunArtifactVerificationError(
                    f"run artifact carrier contains unsupported entry: {relative}"
                )
            before = candidate.stat()
            hasher = hashlib.sha256()
            byte_size = 0
            try:
                with candidate.open("rb") as handle:
                    for chunk in iter(
                        lambda: handle.read(1024 * 1024),
                        b"",
                    ):
                        hasher.update(chunk)
                        byte_size += len(chunk)
            except OSError as exc:
                raise RunArtifactVerificationError(
                    f"run artifact carrier file cannot be read: {relative}"
                ) from exc
            after = candidate.stat()
            before_identity = (
                before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns,
            )
            after_identity = (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns,
            )
            if before_identity != after_identity or byte_size != after.st_size:
                raise RunArtifactVerificationError(
                    f"run artifact carrier changed during GC scan: {relative}"
                )
            entries.append(
                ("file", relative, hasher.hexdigest(), byte_size)
            )
            observed_kinds.append(("file", relative))
            total_bytes += byte_size

        final_kinds: list[tuple[str, str]] = []
        for candidate in sorted(
            root.rglob("*"),
            key=lambda value: value.relative_to(root).as_posix(),
        ):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                final_kinds.append(("symlink", relative))
            elif candidate.is_dir():
                final_kinds.append(("dir", relative))
            elif candidate.is_file():
                final_kinds.append(("file", relative))
            else:
                final_kinds.append(("other", relative))
        if final_kinds != observed_kinds:
            raise RunArtifactVerificationError(
                "run artifact carrier changed during GC tree scan"
            )
        digest = canonical_digest(
            {
                "schema": "run-artifact.carrier-tree.v1",
                "run_id": self.run_id,
                "entries": entries,
            }
        )
        return digest, len(entries), total_bytes

    @staticmethod
    def _require_gc_identity(
        gc: RunArtifactGcAssessment,
        current: tuple[str, int, int],
    ) -> None:
        if current != (
            gc.tree_digest,
            gc.entry_count,
            gc.total_bytes,
        ):
            raise RuntimeError(
                "run artifact carrier changed after GC assessment"
            )

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
        self._require_active()
        if type(kind) is not RunArtifactKind:
            raise ValueError("run artifact kind must be RunArtifactKind")
        return str(self._resolve_ref(name, create_parent=True))

    def directory(self, name: str, *, kind: RunArtifactKind) -> str:
        self._require_active()
        if type(kind) is not RunArtifactKind:
            raise ValueError("run artifact kind must be RunArtifactKind")
        target = self._resolve_ref(name, create_parent=False)
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def publish_json(self, name: str, payload: JsonValue, *, kind: RunArtifactKind) -> str:
        self._require_active()
        body = canonical_bytes(payload, indent=2).decode("utf-8") + "\n"
        return self.publish_text(name, body, kind=kind)

    def publish_text(self, name: str, content: str, *, kind: RunArtifactKind) -> str:
        self._require_active()
        target = self._resolve_ref(name, create_parent=True)

        def publish_owned() -> str:
            with InterprocessFileLock(self._process_lock_path):
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
        self._require_active()
        target = self._resolve_ref(name, create_parent=True)
        encoded = canonical_bytes(payload).decode("utf-8") + "\n"

        def append_owned() -> str:
            with InterprocessFileLock(self._process_lock_path):
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
            raise RunArtifactFinalizationError(
                "run artifact generation ledger conflicts with finalized receipt"
            )
        atomic_replace_bytes(ledger, payload)

    def finalize(
        self,
        artifact_ref: str,
        *,
        kind: RunArtifactKind,
        record_stream: bool,
    ) -> RunArtifactSnapshotReceipt:
        self._require_active()
        def finalize_owned() -> RunArtifactSnapshotReceipt:
            with InterprocessFileLock(self._process_lock_path):
                return self._finalize_locked(
                    artifact_ref,
                    kind=kind,
                    record_stream=record_stream,
                )

        return self._writer_actor.call(f"finalize:{artifact_ref}", finalize_owned)

    def _finalize_locked(
        self,
        artifact_ref: str,
        *,
        kind: RunArtifactKind,
        record_stream: bool,
    ) -> RunArtifactSnapshotReceipt:
        seal = self._seal_path(artifact_ref)
        if seal.exists():
            recorded = self._decode_receipt(
                self._read_bytes(
                    seal,
                    error_type=RunArtifactFinalizationError,
                    label="seal",
                ),
                error_type=RunArtifactFinalizationError,
            )
            if (
                recorded.artifact_kind is not kind
                or (recorded.record_count is not None) is not record_stream
            ):
                raise RunArtifactFinalizationError(
                    "run artifact is already sealed with different semantics"
                )
            self._ensure_generation_index(recorded)
            try:
                return self._verify_finalized_unlocked(recorded)
            except RunArtifactVerificationError as exc:
                raise RunArtifactFinalizationError(
                    "sealed run artifact no longer matches its receipt"
                ) from exc

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
            raise RunArtifactFinalizationError(
                "finalized run artifact failed immediate verification"
            ) from exc
        self._ensure_generation_index(receipt)
        return verified

    def verify_finalized(self, receipt: RunArtifactSnapshotReceipt) -> RunArtifactSnapshotReceipt:
        self._require_active()
        if type(receipt) is not RunArtifactSnapshotReceipt:
            raise RunArtifactVerificationError("run artifact verification requires a typed snapshot receipt")
        if receipt.run_id != self.run_id:
            raise RunArtifactVerificationError("run artifact snapshot belongs to a different run")
        def verify_owned() -> RunArtifactSnapshotReceipt:
            with InterprocessFileLock(self._process_lock_path):
                return self._verify_finalized_unlocked(receipt)

        return self._writer_actor.call(
            f"verify-finalized:{receipt.artifact_ref}",
            verify_owned,
        )


    def assess_gc(
        self,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> RunArtifactGcAssessment:
        validate_durable_carrier_closures(closures)

        def assess_owned() -> RunArtifactGcAssessment:
            with InterprocessFileLock(self._process_lock_path):
                retirement = self._load_retirement()
                if retirement is None:
                    tree_digest, entry_count, total_bytes = (
                        self._tree_identity(self.root)
                    )
                else:
                    tree_digest = str(retirement["tree_digest"])
                    entry_count = int(retirement["entry_count"])
                    total_bytes = int(retirement["total_bytes"])
                return RunArtifactGcAssessment(
                    run_id=self.run_id,
                    tree_digest=tree_digest,
                    entry_count=entry_count,
                    total_bytes=total_bytes,
                    closures=closures,
                )

        return self._writer_actor.call("assess-gc", assess_owned)

    def purge(
        self,
        *,
        gc: RunArtifactGcAssessment,
    ) -> bool:
        if type(gc) is not RunArtifactGcAssessment or gc.run_id != self.run_id:
            raise RuntimeError(
                "run artifact GC assessment does not bind the exact run identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "run artifact physical GC requires complete execution, evidence, "
                "and recovery closure with zero retained references"
            )

        def purge_owned() -> bool:
            quarantine = self._quarantine_path()
            with InterprocessFileLock(self._process_lock_path):
                retirement = self._load_retirement()
                if retirement is None:
                    self._require_gc_identity(
                        gc,
                        self._tree_identity(self.root),
                    )
                    self._publish_retirement(
                        gc,
                        _RunArtifactRetirementPhase.RETIRED,
                    )
                    retirement = self._load_retirement()
                    assert retirement is not None
                else:
                    self._require_gc_identity(
                        gc,
                        (
                            str(retirement["tree_digest"]),
                            int(retirement["entry_count"]),
                            int(retirement["total_bytes"]),
                        ),
                    )
                    if retirement["gc_proof_digest"] != gc.proof_digest:
                        raise RuntimeError(
                            "run artifact GC proof changed across retry"
                        )

                phase = retirement["phase"]
                if phase is _RunArtifactRetirementPhase.RETIRED:
                    live = self.root.exists()
                    quarantined = quarantine.exists()
                    if live and quarantined:
                        raise RuntimeError(
                            "run artifact retirement has split live/quarantine truth"
                        )
                    if quarantined:
                        self._require_gc_identity(
                            gc,
                            self._tree_identity(quarantine),
                        )
                        self._publish_retirement(
                            gc,
                            _RunArtifactRetirementPhase.QUARANTINED,
                        )
                        phase = _RunArtifactRetirementPhase.QUARANTINED
                    elif live:
                        self._require_gc_identity(
                            gc,
                            self._tree_identity(self.root),
                        )
                        quarantine.parent.mkdir(parents=True, exist_ok=True)
                        fsync_directory(quarantine.parent.parent)
                        if quarantine.exists():
                            raise RuntimeError(
                                "run artifact quarantine identity already exists"
                            )
                        try:
                            self.root.rename(quarantine)
                        except OSError:
                            if self.root.exists() or not quarantine.exists():
                                raise
                        fsync_directory(self.root.parent)
                        fsync_directory(quarantine.parent)
                        self._publish_retirement(
                            gc,
                            _RunArtifactRetirementPhase.QUARANTINED,
                        )
                        self._require_gc_identity(
                            gc,
                            self._tree_identity(quarantine),
                        )
                        phase = _RunArtifactRetirementPhase.QUARANTINED
                    else:
                        raise RuntimeError(
                            "retired run artifact carrier disappeared before quarantine"
                        )

                if phase is _RunArtifactRetirementPhase.QUARANTINED:
                    if self.root.exists():
                        raise RuntimeError(
                            "run artifact live root reappeared after quarantine"
                        )
                    if quarantine.exists():
                        if quarantine.is_symlink() or not quarantine.is_dir():
                            raise RuntimeError(
                                "run artifact quarantine is not an owned directory"
                            )
                        shutil.rmtree(quarantine)
                        fsync_directory(quarantine.parent)
                    self._publish_retirement(
                        gc,
                        _RunArtifactRetirementPhase.PURGED,
                    )
                    phase = _RunArtifactRetirementPhase.PURGED

                if phase is not _RunArtifactRetirementPhase.PURGED:
                    raise RuntimeError(
                        "run artifact retirement did not reach terminal state"
                    )
                if self.root.exists() or quarantine.exists():
                    raise RuntimeError(
                        "purged run artifact physical state reappeared"
                    )
                return True

        return self._writer_actor.call("purge", purge_owned)


__all__ = ["DirectoryRunArtifactStore"]
