from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from noetrium_platform.foundation.kernel.kernel import JsonObject, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from ..api import (
    MinecraftWorldBranch,
    MinecraftWorldCut,
    MinecraftWorldCutMetadataStorePort,
    MinecraftWorldCutPort,
    MinecraftWorldQuiescencePort,
)
from .world_copy import FilesystemMinecraftWorldCopier, MinecraftWorldCopier
from .world_cut_integrity import (
    MinecraftWorldCutError,
    file_ref as _file_ref,
    local_path as _local_path,
    manifest_digest as _manifest_digest,
    metadata_bytes as _metadata_bytes,
    path_from_ref as _path_from_ref,
    safe_child as _safe_child,
    safe_exception_message as _safe_exception_message,
    tree_manifest as _tree_manifest,
    validated_manifest as _validated_manifest,
    validate_source as _validate_source,
    within as _within,
)

_CUT_SCHEMA = "minecraft-world-cut.v1"
_BRANCH_SCHEMA = "minecraft-world-branch.v1"


class _CallableMetadataStore(MinecraftWorldCutMetadataStorePort):
    def __init__(self, writer: Callable[[Path, bytes], None]) -> None:
        self._writer = writer

    def publish(self, path: str, payload: bytes) -> None:
        self._writer(Path(path), payload)


class FilesystemMinecraftWorldCutMetadataStore(MinecraftWorldCutMetadataStorePort):
    """Default durable metadata adapter for the local world-cut provider."""

    def publish(self, path: str, payload: bytes) -> None:
        atomic_replace_bytes(Path(path), payload)


class FilesystemMinecraftWorldCutProvider(MinecraftWorldCutPort):
    """Crash-aware local implementation of the MC world-cut/branch seam."""

    def __init__(
        self,
        *,
        quiescence: MinecraftWorldQuiescencePort,
        snapshot_root: str | Path,
        branch_root: str | Path,
        copier: MinecraftWorldCopier | None = None,
        metadata_writer: Callable[[Path, bytes], None] | None = None,
        metadata_store: MinecraftWorldCutMetadataStorePort | None = None,
    ) -> None:
        self.quiescence = quiescence
        self.snapshot_root = _local_path(str(snapshot_root), field="snapshot_root")
        self.branch_root = _local_path(str(branch_root), field="branch_root")
        if self.snapshot_root == self.branch_root or _within(self.snapshot_root, self.branch_root) or _within(self.branch_root, self.snapshot_root):
            raise ValueError("snapshot_root and branch_root must be disjoint")
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        self.branch_root.mkdir(parents=True, exist_ok=True)
        self.copier = copier or FilesystemMinecraftWorldCopier()
        if metadata_writer is not None and metadata_store is not None:
            raise ValueError("provide metadata_store or metadata_writer, not both")
        if metadata_store is not None:
            self.metadata_store = metadata_store
        elif metadata_writer is not None:
            self.metadata_store = _CallableMetadataStore(metadata_writer)
        else:
            self.metadata_store = FilesystemMinecraftWorldCutMetadataStore()

    @staticmethod
    def _identity_path(root: Path, identity: str) -> Path:
        return root / hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _cut_dir(self, cut_id: str) -> Path:
        return self._identity_path(self.snapshot_root / "cuts", cut_id)

    def _publish_metadata(self, path: Path, value: JsonObject) -> None:
        self.metadata_store.publish(str(path), _metadata_bytes(value))

    def _read_cut(self, cut: MinecraftWorldCut) -> tuple[Path, Mapping[str, Any]]:
        payload = _path_from_ref(cut.snapshot_ref)
        manifest_path = _path_from_ref(cut.manifest_ref)
        if not _within(payload, self.snapshot_root) or not _within(manifest_path, self.snapshot_root):
            raise MinecraftWorldCutError("SNAPSHOT_REF_OUTSIDE_PROVIDER_ROOT", cut.cut_id)
        if not payload.is_dir() or not manifest_path.is_file():
            raise MinecraftWorldCutError("SNAPSHOT_MISSING", cut.cut_id)
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_INVALID", _safe_exception_message(exc)) from exc
        if not isinstance(document, dict) or document.get("schema_version") != _CUT_SCHEMA:
            raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_SCHEMA", cut.cut_id)
        expected = _validated_manifest(document.get("files"), source=str(manifest_path))
        if _manifest_digest(expected) != cut.manifest_digest or document.get("manifest_digest") != cut.manifest_digest:
            raise MinecraftWorldCutError("SNAPSHOT_MANIFEST_DIGEST", cut.cut_id)
        if (
            document.get("cut_id") != cut.cut_id
            or document.get("level_name") != cut.level_name
            or document.get("server_contract_digest") != cut.server_contract_digest
            or document.get("process_identity_digest") != cut.process_identity_digest
            or document.get("save_evidence_ref") != cut.save_evidence_ref
        ):
            raise MinecraftWorldCutError("SNAPSHOT_IDENTITY_MISMATCH", cut.cut_id)
        actual = _tree_manifest(payload)
        if actual != expected:
            raise MinecraftWorldCutError("SNAPSHOT_CONTENT_MISMATCH", cut.cut_id)
        return payload, document

    def capture(
        self,
        *,
        session_id: str,
        context: Any,
    ) -> MinecraftWorldCut:
        quiescence = self.quiescence.save_and_quiesce(session_id=session_id, context=context)
        capture_error: BaseException | None = None
        cut: MinecraftWorldCut | None = None
        try:
            source = _local_path(quiescence.source_workdir, field="source_workdir")
            if _within(source, self.snapshot_root) or _within(source, self.branch_root):
                raise MinecraftWorldCutError("SOURCE_ROOT_OVERLAP", str(source))
            _validate_source(source, quiescence.level_name)
            manifest = _tree_manifest(source)
            digest = _manifest_digest(manifest)
            cut_id = "minecraft-cut:" + canonical_digest(
                {
                    "quiescence_digest": quiescence.digest(),
                    "manifest_digest": digest,
                }
            )
            cut_dir = self._cut_dir(cut_id)
            payload = cut_dir / "payload"
            manifest_path = cut_dir / "manifest.json"
            if cut_dir.exists():
                cut = MinecraftWorldCut(
                    cut_id,
                    _file_ref(payload),
                    _file_ref(manifest_path),
                    quiescence.level_name,
                    quiescence.server_contract_digest,
                    quiescence.process_identity_digest,
                    digest,
                    quiescence.save_evidence_ref,
                )
                self._read_cut(cut)
            else:
                cut_parent = cut_dir.parent
                cut_parent.mkdir(parents=True, exist_ok=True)
                temporary = Path(tempfile.mkdtemp(prefix=".minecraft-cut-", dir=str(cut_parent)))
                try:
                    temporary_payload = temporary / "payload"
                    self.copier.copy(source, temporary_payload)
                    if _tree_manifest(temporary_payload) != manifest:
                        raise MinecraftWorldCutError("CUT_COPY_DIGEST_MISMATCH", cut_id)
                    self._publish_metadata(
                        temporary / "manifest.json",
                        {
                            "schema_version": _CUT_SCHEMA,
                            "cut_id": cut_id,
                            "level_name": quiescence.level_name,
                            "server_contract_digest": quiescence.server_contract_digest,
                            "process_identity_digest": quiescence.process_identity_digest,
                            "quiescence_digest": quiescence.digest(),
                            "manifest_digest": digest,
                            "save_evidence_ref": quiescence.save_evidence_ref,
                            "files": manifest,
                        },
                    )
                    try:
                        temporary.rename(cut_dir)
                    except FileExistsError:
                        pass
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                cut = MinecraftWorldCut(
                    cut_id,
                    _file_ref(payload),
                    _file_ref(manifest_path),
                    quiescence.level_name,
                    quiescence.server_contract_digest,
                    quiescence.process_identity_digest,
                    digest,
                    quiescence.save_evidence_ref,
                )
                self._read_cut(cut)
        except BaseException as exc:
            capture_error = exc

        try:
            self.quiescence.resume(quiescence, session_id=session_id, context=context)
        except BaseException as exc:
            code = "CAPTURE_AND_RESUME_FAILED" if capture_error is not None else "RESUME_FAILED"
            detail = f"resume={type(exc).__name__}: {exc}"
            if capture_error is not None:
                detail = f"capture={type(capture_error).__name__}: {capture_error}; {detail}"
            raise MinecraftWorldCutError(code, detail) from exc
        if capture_error is not None:
            if isinstance(capture_error, (KeyboardInterrupt, SystemExit)):
                raise capture_error
            raise capture_error
        assert cut is not None
        return cut

    def materialize_branch(
        self,
        cut: MinecraftWorldCut,
        *,
        branch_id: str,
        destination_workdir: str,
    ) -> MinecraftWorldBranch:
        if not branch_id.strip():
            raise MinecraftWorldCutError("BRANCH_ID_REQUIRED", "branch_id is empty")
        destination = _safe_child(_local_path(destination_workdir, field="destination_workdir"), self.branch_root, field="destination_workdir")
        payload, document = self._read_cut(cut)
        if destination.exists():
            raise MinecraftWorldCutError("BRANCH_DESTINATION_EXISTS", str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.copier.copy(payload, destination)
            if _tree_manifest(destination) != _validated_manifest(document.get("files"), source=str(destination)):
                raise MinecraftWorldCutError("BRANCH_COPY_DIGEST_MISMATCH", branch_id)
            cleanup_ref = "minecraft-branch-cleanup:" + canonical_digest(
                {"branch_id": branch_id, "cut_id": cut.cut_id, "workdir": str(destination)}
            )
            self._publish_metadata(
                destination / "branch.manifest.json",
                {
                    "schema_version": _BRANCH_SCHEMA,
                    "branch_id": branch_id,
                    "cut_id": cut.cut_id,
                    "level_name": cut.level_name,
                    "manifest_digest": cut.manifest_digest,
                    "cleanup_ref": cleanup_ref,
                },
            )
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            raise
        return MinecraftWorldBranch(
            branch_id,
            cut.cut_id,
            str(destination),
            cut.level_name,
            cut.manifest_digest,
            cleanup_ref,
        )

    def release_branch(self, branch: MinecraftWorldBranch) -> str:
        workdir = _safe_child(_local_path(branch.workdir, field="branch.workdir"), self.branch_root, field="branch.workdir")
        manifest_path = workdir / "branch.manifest.json"
        if not manifest_path.is_file():
            raise MinecraftWorldCutError("BRANCH_MANIFEST_MISSING", str(workdir))
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MinecraftWorldCutError("BRANCH_MANIFEST_INVALID", _safe_exception_message(exc)) from exc
        expected = {
            "schema_version": _BRANCH_SCHEMA,
            "branch_id": branch.branch_id,
            "cut_id": branch.cut_id,
            "level_name": branch.level_name,
            "manifest_digest": branch.manifest_digest,
            "cleanup_ref": branch.cleanup_ref,
        }
        if document != expected:
            raise MinecraftWorldCutError("BRANCH_IDENTITY_MISMATCH", str(workdir))
        try:
            shutil.rmtree(workdir)
        except OSError as exc:
            raise MinecraftWorldCutError(
                "BRANCH_RELEASE_FAILED",
                f"{workdir}: {type(exc).__name__}: {exc}",
            ) from exc
        return branch.cleanup_ref

__all__ = [
    "FilesystemMinecraftWorldCutMetadataStore",
    "FilesystemMinecraftWorldCutProvider",
]
