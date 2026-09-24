from __future__ import annotations

import shutil
from enum import StrEnum
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
    fsync_directory,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayoutPort,
    ManagedDirectoryKind,
    WorkspaceAllocation,
    WorkspaceGcAssessment,
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
    WorkspaceReferenceClosure,
)
from noetrium_platform.foundation.governance.api import (
    ScopeIdentity,
    scope_from_data,
    scope_to_data,
)


_WORKSPACE_SCHEMA = "resource.workspace-allocation.v2"
_WORKSPACE_FIELDS = {"workspace_id", "scope", "category", "owner", "note"}
_WORKSPACE_RETIREMENT_SCHEMA = "resource.workspace-retirement.v2"
_WORKSPACE_RETIREMENT_FIELDS = {
    "workspace_identity_digest",
    "workspace_metadata_digest",
    "gc_proof_digest",
    "phase",
}


class _WorkspaceRetirementPhase(StrEnum):
    RETIRED = "retired"
    QUARANTINED = "quarantined"
    PURGED = "purged"


class LocalWorkspaceManager:
    """Durable, terminal-identity authority for scoped workspaces.

    Workspace contents are recovery carriers, so they are never age-GC'd by this
    authority. Explicit deletion publishes a durable retirement tombstone before
    filesystem removal. The same logical workspace identity can therefore never
    silently adopt residue from an older lifetime.
    """

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._directories = directories

    @property
    def _root(self) -> Path:
        return self._directories.root(ManagedDirectoryKind.WORKSPACES)

    def _path(self, scope: ScopeIdentity, category: str, workspace_id: str) -> Path:
        self._validate_name(scope.scope_id, "scope_id")
        return (
            self._root
            / scope.kind.value
            / scope.scope_id
            / category
            / workspace_id
        )

    @staticmethod
    def _identity_digest(
        scope: ScopeIdentity,
        category: str,
        workspace_id: str,
    ) -> str:
        return canonical_digest(
            {
                "schema": "resource.workspace-identity.v1",
                "scope": scope_to_data(scope),
                "category": category,
                "workspace_id": workspace_id,
            }
        )

    def _lock_path(
        self,
        scope: ScopeIdentity,
        category: str,
        workspace_id: str,
    ) -> Path:
        return (
            self._directories.root(ManagedDirectoryKind.LOCKS)
            / "workspaces"
            / f"{self._identity_digest(scope, category, workspace_id)}.lock"
        )

    def _retired_path(
        self,
        scope: ScopeIdentity,
        category: str,
        workspace_id: str,
    ) -> Path:
        return (
            self._root
            / ".retired"
            / f"{self._identity_digest(scope, category, workspace_id)}.sha256"
        )

    def _quarantine_path(
        self,
        scope: ScopeIdentity,
        category: str,
        workspace_id: str,
    ) -> Path:
        return (
            self._root
            / ".retired-workspaces"
            / self._identity_digest(scope, category, workspace_id)
        )

    @staticmethod
    def _payload(
        workspace_id: str,
        scope: ScopeIdentity,
        category: str,
        owner: str | None,
        note: str | None,
    ) -> dict[str, object]:
        return {
            "workspace_id": workspace_id,
            "scope": scope_to_data(scope),
            "category": category,
            "owner": owner,
            "note": note,
        }

    def allocate_workspace(
        self,
        workspace_id: str,
        *,
        scope: ScopeIdentity,
        category: str = "default",
        owner: str | None = None,
        note: str | None = None,
    ) -> WorkspaceAllocation:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        self._validate_optional_text(owner, "owner")
        self._validate_optional_text(note, "note")
        path = self._path(scope, category, workspace_id)
        payload = self._payload(workspace_id, scope, category, owner, note)

        with InterprocessFileLock(
            self._lock_path(scope, category, workspace_id)
        ):
            if self._retired_path(scope, category, workspace_id).exists():
                raise RuntimeError(
                    "workspace identity is retired and cannot be reused: "
                    f"{workspace_id}"
                )

            metadata = path / ".workspace.json"
            if path.exists():
                if path.is_symlink() or not path.is_dir():
                    raise RuntimeError(
                        f"workspace path is not an owned directory: {path}"
                    )
                if metadata.exists():
                    current = self._decode_metadata(self._root, metadata)
                    expected = WorkspaceAllocation(
                        workspace_id,
                        scope,
                        category,
                        path,
                        owner,
                        note,
                    )
                    if current != expected:
                        raise RuntimeError(
                            "workspace identity already exists with different "
                            f"metadata: {workspace_id}"
                        )
                    return current
                # mkdir may have committed immediately before metadata
                # publication. An empty directory is the only residue that can
                # be safely completed; arbitrary files are never adopted.
                if any(path.iterdir()):
                    raise RuntimeError(
                        "workspace path contains unowned residue without "
                        f"authoritative metadata: {workspace_id}"
                    )
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.mkdir()
                fsync_directory(path.parent)

            allocation = WorkspaceAllocation(
                workspace_id,
                scope,
                category,
                path,
                owner,
                note,
            )
            atomic_replace_bytes(
                metadata,
                encode_checksummed_document(_WORKSPACE_SCHEMA, payload),
            )
            return allocation

    def list_workspaces(
        self,
        *,
        scope: ScopeIdentity | None = None,
        category: str | None = None,
    ) -> tuple[WorkspaceAllocation, ...]:
        root = self._root
        if scope is not None:
            self._validate_name(scope.scope_id, "scope_id")
        if category is not None:
            self._validate_name(category, "category")
        values = [
            self._decode_metadata(root, metadata)
            for metadata in sorted(
                self._metadata_paths(root, scope=scope, category=category)
            )
        ]
        return tuple(values)

    @staticmethod
    def _metadata_paths(
        root: Path,
        *,
        scope: ScopeIdentity | None,
        category: str | None,
    ):
        if scope is not None:
            scope_root = root / scope.kind.value / scope.scope_id
            if category is not None:
                return (scope_root / category).glob("*/.workspace.json")
            return scope_root.glob("*/*/.workspace.json")
        if category is not None:
            return root.glob(f"*/*/{category}/*/.workspace.json")
        return root.glob("*/*/*/*/.workspace.json")

    def _decode_metadata(
        self,
        root: Path,
        metadata: Path,
    ) -> WorkspaceAllocation:
        try:
            decoded = decode_checksummed_document(
                metadata.read_bytes(),
                expected_schema=_WORKSPACE_SCHEMA,
            ).payload
        except (OSError, ChecksummedDocumentError) as exc:
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.DOCUMENT_INTEGRITY
            ) from exc
        if set(decoded) != _WORKSPACE_FIELDS:
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.PAYLOAD_SHAPE
            )
        try:
            workspace_id = str(decoded["workspace_id"])
            category = str(decoded["category"])
            scope = scope_from_data(decoded["scope"])
            owner_raw = decoded["owner"]
            note_raw = decoded["note"]
            if owner_raw is not None and not isinstance(owner_raw, str):
                raise TypeError("owner must be string or null")
            if note_raw is not None and not isinstance(note_raw, str):
                raise TypeError("note must be string or null")
            self._validate_name(workspace_id, "workspace_id")
            self._validate_name(category, "category")
            self._validate_name(scope.scope_id, "scope_id")
            self._validate_optional_text(owner_raw, "owner")
            self._validate_optional_text(note_raw, "note")
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.PAYLOAD_SHAPE
            ) from exc
        expected_path = self._path(scope, category, workspace_id)
        if metadata.parent != expected_path or not metadata.is_relative_to(root):
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.IDENTITY_MISMATCH
            )
        return WorkspaceAllocation(
            workspace_id=workspace_id,
            scope=scope,
            category=category,
            path=metadata.parent,
            owner=owner_raw,
            note=note_raw,
        )

    def assess_workspace_gc(
        self,
        workspace_id: str,
        *,
        scope: ScopeIdentity,
        category: str = "default",
        closures: tuple[WorkspaceReferenceClosure, ...] = (),
    ) -> WorkspaceGcAssessment:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        path = self._path(scope, category, workspace_id)
        retired = self._retired_path(scope, category, workspace_id)
        with InterprocessFileLock(
            self._lock_path(scope, category, workspace_id)
        ):
            if not path.exists() and not retired.exists():
                raise KeyError(
                    "workspace identity does not exist: "
                    f"{workspace_id}"
                )
            if path.exists():
                if path.is_symlink() or not path.is_dir():
                    raise RuntimeError(
                        f"workspace path is not an owned directory: {path}"
                    )
                metadata = path / ".workspace.json"
                if not metadata.is_file():
                    raise RuntimeError(
                        "workspace GC assessment requires authoritative metadata: "
                        f"{workspace_id}"
                    )
                current = self._decode_metadata(self._root, metadata)
                if (
                    current.workspace_id != workspace_id
                    or current.scope != scope
                    or current.category != category
                ):
                    raise RuntimeError(
                        "workspace GC assessment identity drifted"
                    )
            return WorkspaceGcAssessment(
                workspace_id=workspace_id,
                scope=scope,
                category=category,
                closures=closures,
            )

    @staticmethod
    def _metadata_digest(allocation: WorkspaceAllocation) -> str:
        return canonical_digest(
            LocalWorkspaceManager._payload(
                allocation.workspace_id,
                allocation.scope,
                allocation.category,
                allocation.owner,
                allocation.note,
            )
        )

    def _decode_retirement(self, path: Path) -> dict[str, str]:
        try:
            payload = decode_checksummed_document(
                path.read_bytes(),
                expected_schema=_WORKSPACE_RETIREMENT_SCHEMA,
            ).payload
        except (OSError, ChecksummedDocumentError) as exc:
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.DOCUMENT_INTEGRITY
            ) from exc
        if set(payload) != _WORKSPACE_RETIREMENT_FIELDS:
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.PAYLOAD_SHAPE
            )
        digest_fields = (
            "workspace_identity_digest",
            "workspace_metadata_digest",
            "gc_proof_digest",
        )
        if any(
            type(payload.get(field_name)) is not str
            or len(str(payload.get(field_name))) != 64
            or any(
                ch not in "0123456789abcdef"
                for ch in str(payload.get(field_name))
            )
            for field_name in digest_fields
        ):
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.PAYLOAD_SHAPE
            )
        try:
            phase = _WorkspaceRetirementPhase(str(payload["phase"]))
        except (KeyError, ValueError) as exc:
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.PAYLOAD_SHAPE
            ) from exc
        return {
            "workspace_identity_digest": str(
                payload["workspace_identity_digest"]
            ),
            "workspace_metadata_digest": str(
                payload["workspace_metadata_digest"]
            ),
            "gc_proof_digest": str(payload["gc_proof_digest"]),
            "phase": phase.value,
        }

    @staticmethod
    def _retirement_payload(
        *,
        workspace_identity_digest: str,
        workspace_metadata_digest: str,
        gc_proof_digest: str,
        phase: _WorkspaceRetirementPhase,
    ) -> dict[str, str]:
        return {
            "workspace_identity_digest": workspace_identity_digest,
            "workspace_metadata_digest": workspace_metadata_digest,
            "gc_proof_digest": gc_proof_digest,
            "phase": phase.value,
        }

    @staticmethod
    def _publish_retirement(
        path: Path,
        *,
        workspace_identity_digest: str,
        workspace_metadata_digest: str,
        gc_proof_digest: str,
        phase: _WorkspaceRetirementPhase,
    ) -> None:
        atomic_replace_bytes(
            path,
            encode_checksummed_document(
                _WORKSPACE_RETIREMENT_SCHEMA,
                LocalWorkspaceManager._retirement_payload(
                    workspace_identity_digest=workspace_identity_digest,
                    workspace_metadata_digest=workspace_metadata_digest,
                    gc_proof_digest=gc_proof_digest,
                    phase=phase,
                ),
            ),
        )

    def _validate_live_workspace_for_retirement(
        self,
        path: Path,
        *,
        workspace_id: str,
        scope: ScopeIdentity,
        category: str,
        expected_metadata_digest: str | None = None,
    ) -> WorkspaceAllocation:
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(
                f"workspace path is not an owned directory: {path}"
            )
        metadata = path / ".workspace.json"
        if not metadata.is_file():
            raise RuntimeError(
                "workspace retirement requires authoritative metadata: "
                f"{workspace_id}"
            )
        current = self._decode_metadata(self._root, metadata)
        if (
            current.workspace_id != workspace_id
            or current.scope != scope
            or current.category != category
        ):
            raise RuntimeError(
                "workspace retirement identity drifted from authoritative metadata"
            )
        digest = self._metadata_digest(current)
        if (
            expected_metadata_digest is not None
            and digest != expected_metadata_digest
        ):
            raise RuntimeError(
                "workspace retirement metadata changed after durable retirement"
            )
        return current

    @staticmethod
    def _move_to_quarantine(path: Path, quarantine: Path) -> None:
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        fsync_directory(quarantine.parent.parent)
        if quarantine.exists():
            raise RuntimeError(
                f"workspace quarantine identity already exists: {quarantine}"
            )
        try:
            path.rename(quarantine)
        except OSError:
            # Rename may have committed before the caller observed an I/O error.
            if path.exists() or not quarantine.exists():
                raise
        fsync_directory(path.parent)
        fsync_directory(quarantine.parent)

    @staticmethod
    def _purge_quarantine(quarantine: Path) -> None:
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise RuntimeError(
                f"workspace quarantine is not an owned directory: {quarantine}"
            )
        shutil.rmtree(quarantine)
        fsync_directory(quarantine.parent)

    def remove_workspace(
        self,
        workspace_id: str,
        *,
        scope: ScopeIdentity,
        category: str = "default",
        gc: WorkspaceGcAssessment,
    ) -> bool:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        expected_identity = self._identity_digest(
            scope,
            category,
            workspace_id,
        )
        if (
            type(gc) is not WorkspaceGcAssessment
            or gc.workspace_id != workspace_id
            or gc.scope != scope
            or gc.category != category
            or gc.workspace_identity_digest != expected_identity
        ):
            raise RuntimeError(
                "workspace GC assessment does not bind the exact workspace identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "workspace GC requires complete execution, evidence, and recovery "
                "closure with zero retained references"
            )

        path = self._path(scope, category, workspace_id)
        retired = self._retired_path(scope, category, workspace_id)
        quarantine = self._quarantine_path(scope, category, workspace_id)

        with InterprocessFileLock(
            self._lock_path(scope, category, workspace_id)
        ):
            if not retired.exists():
                if not path.exists():
                    return False
                if quarantine.exists():
                    raise RuntimeError(
                        "workspace quarantine exists without durable retirement proof"
                    )
                current = self._validate_live_workspace_for_retirement(
                    path,
                    workspace_id=workspace_id,
                    scope=scope,
                    category=category,
                )
                metadata_digest = self._metadata_digest(current)
                self._publish_retirement(
                    retired,
                    workspace_identity_digest=expected_identity,
                    workspace_metadata_digest=metadata_digest,
                    gc_proof_digest=gc.proof_digest,
                    phase=_WorkspaceRetirementPhase.RETIRED,
                )
            retirement = self._decode_retirement(retired)
            if retirement["workspace_identity_digest"] != expected_identity:
                raise RuntimeError(
                    "workspace retirement identity does not match derived identity"
                )
            if retirement["gc_proof_digest"] != gc.proof_digest:
                raise RuntimeError(
                    "workspace retirement GC proof changed across retry"
                )

            phase = _WorkspaceRetirementPhase(retirement["phase"])
            metadata_digest = retirement["workspace_metadata_digest"]

            if phase is _WorkspaceRetirementPhase.PURGED:
                if quarantine.exists():
                    raise RuntimeError(
                        "purged workspace quarantine reappeared"
                    )
                if path.exists():
                    raise RuntimeError(
                        "purged workspace live path reappeared as unowned residue"
                    )
                return True

            if phase is _WorkspaceRetirementPhase.RETIRED:
                if path.exists() and quarantine.exists():
                    raise RuntimeError(
                        "workspace retirement split truth: live and quarantine both exist"
                    )
                if quarantine.exists():
                    # Rename committed before the phase publication became
                    # durable. The quarantine identity is terminal and exact.
                    self._publish_retirement(
                        retired,
                        workspace_identity_digest=expected_identity,
                        workspace_metadata_digest=metadata_digest,
                        gc_proof_digest=gc.proof_digest,
                        phase=_WorkspaceRetirementPhase.QUARANTINED,
                    )
                    phase = _WorkspaceRetirementPhase.QUARANTINED
                elif path.exists():
                    self._validate_live_workspace_for_retirement(
                        path,
                        workspace_id=workspace_id,
                        scope=scope,
                        category=category,
                        expected_metadata_digest=metadata_digest,
                    )
                    self._move_to_quarantine(path, quarantine)
                    self._publish_retirement(
                        retired,
                        workspace_identity_digest=expected_identity,
                        workspace_metadata_digest=metadata_digest,
                        gc_proof_digest=gc.proof_digest,
                        phase=_WorkspaceRetirementPhase.QUARANTINED,
                    )
                    phase = _WorkspaceRetirementPhase.QUARANTINED
                else:
                    raise RuntimeError(
                        "retired workspace lost both live and quarantine carriers"
                    )

            if phase is _WorkspaceRetirementPhase.QUARANTINED:
                if path.exists():
                    raise RuntimeError(
                        "quarantined workspace live path reappeared as unowned residue"
                    )
                if quarantine.exists():
                    self._purge_quarantine(quarantine)
                self._publish_retirement(
                    retired,
                    workspace_identity_digest=expected_identity,
                    workspace_metadata_digest=metadata_digest,
                    gc_proof_digest=gc.proof_digest,
                    phase=_WorkspaceRetirementPhase.PURGED,
                )
                return True

            raise RuntimeError(
                f"unsupported workspace retirement phase: {phase.value}"
            )

    @staticmethod
    def _validate_name(value: str, label: str) -> None:
        if (
            type(value) is not str
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError(f"invalid {label}")

    @staticmethod
    def _validate_optional_text(value: str | None, label: str) -> None:
        if value is not None and (
            type(value) is not str or not value.strip()
        ):
            raise ValueError(f"workspace {label} must be non-empty text or None")


__all__ = ["LocalWorkspaceManager"]
