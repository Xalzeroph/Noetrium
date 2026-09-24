from __future__ import annotations

import shutil
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
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
)
from noetrium_platform.foundation.governance.api import (
    ScopeIdentity,
    scope_from_data,
    scope_to_data,
)


_WORKSPACE_SCHEMA = "resource.workspace-allocation.v2"
_WORKSPACE_FIELDS = {"workspace_id", "scope", "category", "owner", "note"}


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

    def remove_workspace(
        self,
        workspace_id: str,
        *,
        scope: ScopeIdentity,
        category: str = "default",
    ) -> bool:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        path = self._path(scope, category, workspace_id)
        retired = self._retired_path(scope, category, workspace_id)

        with InterprocessFileLock(
            self._lock_path(scope, category, workspace_id)
        ):
            if retired.exists():
                # A prior call may have crashed after durable retirement but
                # before the directory tree fully disappeared. Retirement is
                # terminal, so retry may finish deleting only this exact path.
                if path.exists():
                    if path.is_symlink() or not path.is_dir():
                        raise RuntimeError(
                            f"retired workspace path is not a directory: {path}"
                        )
                    shutil.rmtree(path)
                    fsync_directory(path.parent)
                return True

            if not path.exists():
                return False
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError(
                    f"workspace path is not an owned directory: {path}"
                )

            metadata = path / ".workspace.json"
            if not metadata.is_file():
                raise RuntimeError(
                    "workspace removal requires authoritative metadata: "
                    f"{workspace_id}"
                )
            current = self._decode_metadata(self._root, metadata)
            payload = self._payload(
                current.workspace_id,
                current.scope,
                current.category,
                current.owner,
                current.note,
            )
            # Publish retirement first. If process death happens after this
            # point, allocation is permanently fenced while remove() remains
            # safe to retry against the same derived directory.
            atomic_replace_bytes(
                retired,
                (canonical_digest(payload) + "\n").encode("ascii"),
            )
            shutil.rmtree(path)
            fsync_directory(path.parent)
            return True

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
