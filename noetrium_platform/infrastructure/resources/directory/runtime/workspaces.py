from __future__ import annotations

import shutil
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayoutPort,
    ManagedDirectoryKind,
    WorkspaceAllocation,
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, scope_from_data, scope_to_data


_WORKSPACE_SCHEMA = "resource.workspace-allocation.v2"
_WORKSPACE_FIELDS = {"workspace_id", "scope", "category", "owner", "note"}


class LocalWorkspaceManager:
    """Scoped workspace durable-metadata authority.

    Directory location is derived from scope/category/workspace identity. It is
    deliberately not duplicated inside the durable metadata document. Listing
    traverses only the fixed workspace layout depth and prunes by supplied scope
    and category instead of recursively walking arbitrary workspace contents.
    """

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._directories = directories

    def _path(self, scope: ScopeIdentity, category: str, workspace_id: str) -> Path:
        self._validate_name(scope.scope_id, "scope_id")
        return (
            self._directories.root(ManagedDirectoryKind.WORKSPACES)
            / scope.kind.value
            / scope.scope_id
            / category
            / workspace_id
        )

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
        path = self._path(scope, category, workspace_id)
        path.mkdir(parents=True, exist_ok=True)
        allocation = WorkspaceAllocation(workspace_id, scope, category, path, owner, note)
        payload = {
            "workspace_id": allocation.workspace_id,
            "scope": scope_to_data(allocation.scope),
            "category": allocation.category,
            "owner": allocation.owner,
            "note": allocation.note,
        }
        atomic_replace_bytes(
            path / ".workspace.json",
            encode_checksummed_document(_WORKSPACE_SCHEMA, payload),
        )
        return allocation

    def list_workspaces(
        self,
        *,
        scope: ScopeIdentity | None = None,
        category: str | None = None,
    ) -> tuple[WorkspaceAllocation, ...]:
        root = self._directories.root(ManagedDirectoryKind.WORKSPACES)
        if scope is not None:
            self._validate_name(scope.scope_id, "scope_id")
        if category is not None:
            self._validate_name(category, "category")
        values = [
            self._decode_metadata(root, metadata)
            for metadata in sorted(self._metadata_paths(root, scope=scope, category=category))
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

    def _decode_metadata(self, root: Path, metadata: Path) -> WorkspaceAllocation:
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
            raise WorkspaceMetadataError(WorkspaceMetadataFailureCode.PAYLOAD_SHAPE)
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
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceMetadataError(WorkspaceMetadataFailureCode.PAYLOAD_SHAPE) from exc
        expected_path = self._path(scope, category, workspace_id)
        if metadata.parent != expected_path or not metadata.is_relative_to(root):
            raise WorkspaceMetadataError(WorkspaceMetadataFailureCode.IDENTITY_MISMATCH)
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
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True

    @staticmethod
    def _validate_name(value: str, label: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"invalid {label}")


__all__ = ["LocalWorkspaceManager"]
