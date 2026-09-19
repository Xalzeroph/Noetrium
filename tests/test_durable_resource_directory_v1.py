from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    encode_checksummed_document,
)
from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayout,
    ManagedDirectoryKind,
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
)
from noetrium_platform.infrastructure.resources.directory.runtime import build_local_directory_authorities
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind, scope_to_data


def _layout(root: Path) -> DirectoryLayout:
    return DirectoryLayout(
        releases=root / "releases",
        runtime=root / "runtime",
        state=root / "state",
        logs=root / "logs",
        model_artifacts=root / "models",
        python_environments=root / "pyenvs",
        cache=root / "cache",
        temp=root / "temp",
        locks=root / "locks",
        workspaces=root / "workspaces",
    )


def test_workspace_metadata_is_checksummed_and_path_is_derived(tmp_path: Path) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-a")
    allocation = authorities.workspaces.allocate_workspace(
        "run-1", scope=scope, category="study", owner="paper-1"
    )
    document = json.loads((allocation.path / ".workspace.json").read_text("utf-8"))
    assert document["schema"] == "resource.workspace-allocation.v2"
    assert "path" not in document["payload"]
    assert document["payload"]["workspace_id"] == "run-1"

    reopened = build_local_directory_authorities(_layout(tmp_path))
    assert reopened.workspaces.list_workspaces(scope=scope, category="study") == (allocation,)


def test_workspace_listing_prunes_nested_non_authority_metadata(tmp_path: Path) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-a")
    allocation = authorities.workspaces.allocate_workspace("run-1", scope=scope, category="study")
    nested = allocation.path / "payload" / "deep" / ".workspace.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("not-json", encoding="utf-8")

    assert authorities.workspaces.list_workspaces(scope=scope, category="study") == (allocation,)


def test_workspace_metadata_tamper_fails_closed(tmp_path: Path) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-a")
    allocation = authorities.workspaces.allocate_workspace("run-1", scope=scope, category="study")
    metadata = allocation.path / ".workspace.json"
    document = json.loads(metadata.read_text("utf-8"))
    document["payload"]["owner"] = "tampered"
    metadata.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(WorkspaceMetadataError) as raised:
        authorities.workspaces.list_workspaces(scope=scope, category="study")
    assert raised.value.code is WorkspaceMetadataFailureCode.DOCUMENT_INTEGRITY


def test_workspace_metadata_cannot_claim_another_identity(tmp_path: Path) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-a")
    allocation = authorities.workspaces.allocate_workspace("run-1", scope=scope, category="study")
    payload = {
        "workspace_id": "run-2",
        "scope": scope_to_data(scope),
        "category": "study",
        "owner": None,
        "note": None,
    }
    (allocation.path / ".workspace.json").write_bytes(
        encode_checksummed_document("resource.workspace-allocation.v2", payload)
    )

    with pytest.raises(WorkspaceMetadataError) as raised:
        authorities.workspaces.list_workspaces(scope=scope, category="study")
    assert raised.value.code is WorkspaceMetadataFailureCode.IDENTITY_MISMATCH
