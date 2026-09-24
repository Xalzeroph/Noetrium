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
    WorkspaceClosureAuthority,
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
    WorkspaceReferenceClosure,
)
from noetrium_platform.infrastructure.resources.directory.runtime import build_local_directory_authorities
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind, scope_to_data


def _closed_workspace_gc(
    authorities,
    workspace_id: str,
    *,
    scope: ScopeIdentity,
    category: str,
):
    return authorities.workspaces.assess_workspace_gc(
        workspace_id,
        scope=scope,
        category=category,
        closures=(
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.EVIDENCE,
                "1" * 64,
                (),
            ),
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.EXECUTION,
                "2" * 64,
                (),
            ),
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.RECOVERY,
                "3" * 64,
                (),
            ),
        ),
    )


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


def test_workspace_exact_reallocation_is_idempotent_without_adopting_new_identity(
    tmp_path: Path,
) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-idempotent")
    first = authorities.workspaces.allocate_workspace(
        "run-stable",
        scope=scope,
        category="study",
        owner="paper-1",
        note="stable",
    )
    payload = first.path / "result.bin"
    payload.write_bytes(b"scientific-state")

    second = authorities.workspaces.allocate_workspace(
        "run-stable",
        scope=scope,
        category="study",
        owner="paper-1",
        note="stable",
    )

    assert second == first
    assert payload.read_bytes() == b"scientific-state"
    with pytest.raises(RuntimeError, match="different metadata"):
        authorities.workspaces.allocate_workspace(
            "run-stable",
            scope=scope,
            category="study",
            owner="paper-2",
            note="stable",
        )


def test_workspace_allocation_refuses_unowned_residue(
    tmp_path: Path,
) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-residue")
    residue = (
        tmp_path
        / "workspaces"
        / scope.kind.value
        / scope.scope_id
        / "study"
        / "run-residue"
    )
    residue.mkdir(parents=True)
    (residue / "old-output.txt").write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unowned residue"):
        authorities.workspaces.allocate_workspace(
            "run-residue",
            scope=scope,
            category="study",
        )
    assert (residue / "old-output.txt").read_text("utf-8") == "old"


def test_removed_workspace_identity_is_terminal(
    tmp_path: Path,
) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-retired")
    allocation = authorities.workspaces.allocate_workspace(
        "run-retired",
        scope=scope,
        category="study",
        owner="paper-1",
    )
    (allocation.path / "payload").write_text("state", encoding="utf-8")

    gc = _closed_workspace_gc(
        authorities,
        "run-retired",
        scope=scope,
        category="study",
    )
    assert authorities.workspaces.remove_workspace(
        "run-retired",
        scope=scope,
        category="study",
        gc=gc,
    )
    assert not allocation.path.exists()
    assert authorities.workspaces.remove_workspace(
        "run-retired",
        scope=scope,
        category="study",
        gc=gc,
    )
    with pytest.raises(RuntimeError, match="retired and cannot be reused"):
        authorities.workspaces.allocate_workspace(
            "run-retired",
            scope=scope,
            category="study",
            owner="paper-1",
        )


def test_workspace_remove_retries_after_retirement_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-remove-retry")
    allocation = authorities.workspaces.allocate_workspace(
        "run-retry",
        scope=scope,
        category="study",
    )
    (allocation.path / "payload").write_text("state", encoding="utf-8")

    real_rmtree = workspace_runtime.shutil.rmtree
    calls = 0

    def fail_once(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated recursive delete interruption")
        return real_rmtree(path)

    monkeypatch.setattr(workspace_runtime.shutil, "rmtree", fail_once)
    gc = _closed_workspace_gc(
        authorities,
        "run-retry",
        scope=scope,
        category="study",
    )
    with pytest.raises(OSError, match="delete interruption"):
        authorities.workspaces.remove_workspace(
            "run-retry",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert allocation.path.exists()
    with pytest.raises(RuntimeError, match="retired and cannot be reused"):
        authorities.workspaces.allocate_workspace(
            "run-retry",
            scope=scope,
            category="study",
        )

    assert authorities.workspaces.remove_workspace(
        "run-retry",
        scope=scope,
        category="study",
        gc=gc,
    )
    assert calls == 2
    assert not allocation.path.exists()


def test_workspace_gc_fails_closed_without_all_reference_authorities(
    tmp_path: Path,
) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-gc-blocked")
    allocation = authorities.workspaces.allocate_workspace(
        "run-gc-blocked",
        scope=scope,
        category="study",
    )
    partial = authorities.workspaces.assess_workspace_gc(
        "run-gc-blocked",
        scope=scope,
        category="study",
        closures=(
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.EXECUTION,
                "4" * 64,
                (),
            ),
        ),
    )
    assert not partial.closure_complete
    assert not partial.eligible
    with pytest.raises(
        RuntimeError,
        match="complete execution, evidence, and recovery",
    ):
        authorities.workspaces.remove_workspace(
            "run-gc-blocked",
            scope=scope,
            category="study",
            gc=partial,
        )
    assert allocation.path.exists()


@pytest.mark.parametrize(
    ("authority", "reference_id"),
    (
        (WorkspaceClosureAuthority.EXECUTION, "run-resumable"),
        (WorkspaceClosureAuthority.EVIDENCE, "evidence-retained"),
        (WorkspaceClosureAuthority.RECOVERY, "checkpoint-retained"),
    ),
)
def test_workspace_gc_blocks_any_retained_recovery_reference(
    tmp_path: Path,
    authority: WorkspaceClosureAuthority,
    reference_id: str,
) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, f"branch-{authority.value}")
    workspace_id = f"run-{authority.value}"
    allocation = authorities.workspaces.allocate_workspace(
        workspace_id,
        scope=scope,
        category="study",
    )
    closures = tuple(
        WorkspaceReferenceClosure(
            current,
            str(index) * 64,
            (reference_id,) if current is authority else (),
        )
        for index, current in enumerate(
            (
                WorkspaceClosureAuthority.EVIDENCE,
                WorkspaceClosureAuthority.EXECUTION,
                WorkspaceClosureAuthority.RECOVERY,
            ),
            start=5,
        )
    )
    assessment = authorities.workspaces.assess_workspace_gc(
        workspace_id,
        scope=scope,
        category="study",
        closures=closures,
    )
    assert assessment.closure_complete
    assert not assessment.eligible
    with pytest.raises(RuntimeError, match="zero retained references"):
        authorities.workspaces.remove_workspace(
            workspace_id,
            scope=scope,
            category="study",
            gc=assessment,
        )
    assert allocation.path.exists()


def test_workspace_remove_retry_rejects_changed_gc_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-proof-retry")
    allocation = authorities.workspaces.allocate_workspace(
        "run-proof-retry",
        scope=scope,
        category="study",
    )
    real_rmtree = workspace_runtime.shutil.rmtree

    def fail_delete(_path):
        raise OSError("simulated interruption after durable retirement")

    monkeypatch.setattr(workspace_runtime.shutil, "rmtree", fail_delete)
    original = _closed_workspace_gc(
        authorities,
        "run-proof-retry",
        scope=scope,
        category="study",
    )
    with pytest.raises(OSError, match="interruption"):
        authorities.workspaces.remove_workspace(
            "run-proof-retry",
            scope=scope,
            category="study",
            gc=original,
        )

    changed = authorities.workspaces.assess_workspace_gc(
        "run-proof-retry",
        scope=scope,
        category="study",
        closures=(
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.EVIDENCE,
                "a" * 64,
                (),
            ),
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.EXECUTION,
                "b" * 64,
                (),
            ),
            WorkspaceReferenceClosure(
                WorkspaceClosureAuthority.RECOVERY,
                "c" * 64,
                (),
            ),
        ),
    )
    monkeypatch.setattr(workspace_runtime.shutil, "rmtree", real_rmtree)
    with pytest.raises(RuntimeError, match="GC proof changed across retry"):
        authorities.workspaces.remove_workspace(
            "run-proof-retry",
            scope=scope,
            category="study",
            gc=changed,
        )
    assert allocation.path.exists()
    assert authorities.workspaces.remove_workspace(
        "run-proof-retry",
        scope=scope,
        category="study",
        gc=original,
    )
    assert not allocation.path.exists()
