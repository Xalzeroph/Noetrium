from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
)

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
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EVIDENCE,
                "1" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "2" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.RECOVERY,
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

    real_purge = workspace_runtime.purge_directory_contents
    calls = 0

    def fail_once(path, *, expected_generation):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated recursive delete interruption")
        return real_purge(path, expected_generation=expected_generation)

    monkeypatch.setattr(workspace_runtime, "purge_directory_contents", fail_once)
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

    assert not allocation.path.exists()
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    quarantined = tuple(quarantine_root.iterdir())
    assert len(quarantined) == 1
    assert (quarantined[0] / "payload").read_text("utf-8") == "state"
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
    assert not quarantined[0].exists()


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
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
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
        (DurableCarrierClosureAuthority.EXECUTION, "run-resumable"),
        (DurableCarrierClosureAuthority.EVIDENCE, "evidence-retained"),
        (DurableCarrierClosureAuthority.RECOVERY, "checkpoint-retained"),
    ),
)
def test_workspace_gc_blocks_any_retained_recovery_reference(
    tmp_path: Path,
    authority: DurableCarrierClosureAuthority,
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
        DurableCarrierReferenceClosure(
            current,
            str(index) * 64,
            (reference_id,) if current is authority else (),
        )
        for index, current in enumerate(
            (
                DurableCarrierClosureAuthority.EVIDENCE,
                DurableCarrierClosureAuthority.EXECUTION,
                DurableCarrierClosureAuthority.RECOVERY,
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
    real_purge = workspace_runtime.purge_directory_contents

    def fail_delete(_path, *, expected_generation):
        del expected_generation
        raise OSError("simulated interruption after durable retirement")

    monkeypatch.setattr(workspace_runtime, "purge_directory_contents", fail_delete)
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
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EVIDENCE,
                "a" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "b" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.RECOVERY,
                "c" * 64,
                (),
            ),
        ),
    )
    monkeypatch.setattr(workspace_runtime, "purge_directory_contents", real_purge)
    with pytest.raises(RuntimeError, match="GC proof changed across retry"):
        authorities.workspaces.remove_workspace(
            "run-proof-retry",
            scope=scope,
            category="study",
            gc=changed,
        )
    assert not allocation.path.exists()
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    quarantined = tuple(quarantine_root.iterdir())
    assert len(quarantined) == 1
    assert authorities.workspaces.remove_workspace(
        "run-proof-retry",
        scope=scope,
        category="study",
        gc=original,
    )
    assert not allocation.path.exists()
    assert not quarantined[0].exists()



def test_workspace_gc_recovers_rename_committed_before_phase_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-rename-commit")
    allocation = authorities.workspaces.allocate_workspace(
        "run-rename-commit",
        scope=scope,
        category="study",
    )
    payload = allocation.path / "scientific-state.bin"
    payload.write_bytes(b"durable-state")
    gc = _closed_workspace_gc(
        authorities,
        "run-rename-commit",
        scope=scope,
        category="study",
    )

    real_atomic_replace = workspace_runtime.atomic_replace_bytes
    retirement_writes = 0

    def fail_quarantined_publication(path, data):
        nonlocal retirement_writes
        retirement_writes += 1
        if retirement_writes == 2:
            raise OSError(
                "simulated crash after quarantine rename before phase publication"
            )
        return real_atomic_replace(path, data)

    monkeypatch.setattr(
        workspace_runtime,
        "atomic_replace_bytes",
        fail_quarantined_publication,
    )
    with pytest.raises(OSError, match="after quarantine rename"):
        authorities.workspaces.remove_workspace(
            "run-rename-commit",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert not allocation.path.exists()
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    quarantined = tuple(quarantine_root.iterdir())
    assert len(quarantined) == 1
    assert (quarantined[0] / "scientific-state.bin").read_bytes() == b"durable-state"

    monkeypatch.setattr(
        workspace_runtime,
        "atomic_replace_bytes",
        real_atomic_replace,
    )
    assert authorities.workspaces.remove_workspace(
        "run-rename-commit",
        scope=scope,
        category="study",
        gc=gc,
    )
    assert not quarantined[0].exists()


def test_workspace_gc_rejects_quarantine_replacement_after_rename_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-quarantine-replaced")
    allocation = authorities.workspaces.allocate_workspace(
        "run-quarantine-replaced",
        scope=scope,
        category="study",
    )
    (allocation.path / "payload").write_text("owned", encoding="utf-8")
    gc = _closed_workspace_gc(
        authorities,
        "run-quarantine-replaced",
        scope=scope,
        category="study",
    )

    real_atomic_replace = workspace_runtime.atomic_replace_bytes
    retirement_writes = 0

    def fail_after_rename(path, data):
        nonlocal retirement_writes
        retirement_writes += 1
        if retirement_writes == 2:
            raise OSError("simulated crash after rename before phase publication")
        return real_atomic_replace(path, data)

    monkeypatch.setattr(
        workspace_runtime,
        "atomic_replace_bytes",
        fail_after_rename,
    )
    with pytest.raises(OSError, match="after rename"):
        authorities.workspaces.remove_workspace(
            "run-quarantine-replaced",
            scope=scope,
            category="study",
            gc=gc,
        )

    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    (quarantine,) = tuple(quarantine_root.iterdir())
    old_generation = quarantine.with_name(f"{quarantine.name}-original")
    quarantine.rename(old_generation)
    quarantine.mkdir()
    (quarantine / ".workspace.json").write_bytes(
        (old_generation / ".workspace.json").read_bytes()
    )
    foreign = quarantine / "replacement-data"
    foreign.write_text("must-survive", encoding="utf-8")

    monkeypatch.setattr(
        workspace_runtime,
        "atomic_replace_bytes",
        real_atomic_replace,
    )
    with pytest.raises(RuntimeError, match="filesystem generation changed"):
        authorities.workspaces.remove_workspace(
            "run-quarantine-replaced",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert foreign.read_text(encoding="utf-8") == "must-survive"
    assert old_generation.exists()


def test_workspace_gc_recovers_purge_committed_before_terminal_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-purge-commit")
    allocation = authorities.workspaces.allocate_workspace(
        "run-purge-commit",
        scope=scope,
        category="study",
    )
    (allocation.path / "payload").write_text("state", encoding="utf-8")
    gc = _closed_workspace_gc(
        authorities,
        "run-purge-commit",
        scope=scope,
        category="study",
    )

    real_atomic_replace = workspace_runtime.atomic_replace_bytes
    retirement_writes = 0

    def fail_terminal_publication(path, data):
        nonlocal retirement_writes
        retirement_writes += 1
        if retirement_writes == 4:
            raise OSError(
                "simulated crash after quarantine purge before terminal publication"
            )
        return real_atomic_replace(path, data)

    monkeypatch.setattr(
        workspace_runtime,
        "atomic_replace_bytes",
        fail_terminal_publication,
    )
    with pytest.raises(OSError, match="after quarantine purge"):
        authorities.workspaces.remove_workspace(
            "run-purge-commit",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert not allocation.path.exists()
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    (empty_quarantine,) = tuple(quarantine_root.glob("*"))
    assert empty_quarantine.is_dir()
    assert tuple(empty_quarantine.iterdir()) == ()

    monkeypatch.setattr(
        workspace_runtime,
        "atomic_replace_bytes",
        real_atomic_replace,
    )
    assert authorities.workspaces.remove_workspace(
        "run-purge-commit",
        scope=scope,
        category="study",
        gc=gc,
    )
    assert not allocation.path.exists()


def test_workspace_gc_retries_partial_recursive_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-partial-purge")
    allocation = authorities.workspaces.allocate_workspace(
        "run-partial-purge",
        scope=scope,
        category="study",
    )
    nested = allocation.path / "nested"
    nested.mkdir()
    (nested / "payload.bin").write_bytes(b"durable-state")
    gc = _closed_workspace_gc(
        authorities,
        "run-partial-purge",
        scope=scope,
        category="study",
    )

    import noetrium_platform.foundation.kernel.kernel.durability.filesystem_generation as fs_generation

    real_rmtree = fs_generation.shutil.rmtree
    calls = 0

    def partial_then_fail(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            (path / "payload.bin").unlink()
            raise OSError("partial workspace recursive delete interruption")
        real_rmtree(path)

    monkeypatch.setattr(
        fs_generation.shutil,
        "rmtree",
        partial_then_fail,
    )
    with pytest.raises(OSError, match="partial workspace recursive"):
        authorities.workspaces.remove_workspace(
            "run-partial-purge",
            scope=scope,
            category="study",
            gc=gc,
        )

    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    (quarantine,) = tuple(quarantine_root.iterdir())
    assert quarantine.is_dir()
    assert not (quarantine / "nested" / "payload.bin").exists()

    monkeypatch.setattr(
        fs_generation.shutil,
        "rmtree",
        real_rmtree,
    )
    assert authorities.workspaces.remove_workspace(
        "run-partial-purge",
        scope=scope,
        category="study",
        gc=gc,
    )
    assert not quarantine.exists()


def test_workspace_gc_purging_rejects_same_tree_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-purging-replaced")
    allocation = authorities.workspaces.allocate_workspace(
        "run-purging-replaced",
        scope=scope,
        category="study",
    )
    (allocation.path / "payload.bin").write_bytes(b"same-tree")
    gc = _closed_workspace_gc(
        authorities,
        "run-purging-replaced",
        scope=scope,
        category="study",
    )

    real_purge = workspace_runtime.purge_directory_contents

    def fail_before_delete(_path: Path, *, expected_generation) -> None:
        del expected_generation
        raise OSError("crash after durable workspace purging intent")

    monkeypatch.setattr(
        workspace_runtime,
        "purge_directory_contents",
        fail_before_delete,
    )
    with pytest.raises(OSError, match="workspace purging intent"):
        authorities.workspaces.remove_workspace(
            "run-purging-replaced",
            scope=scope,
            category="study",
            gc=gc,
        )

    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    (quarantine,) = tuple(quarantine_root.iterdir())
    original = quarantine.with_name(
        f"{quarantine.name}-original-generation"
    )
    quarantine.rename(original)
    workspace_runtime.shutil.copytree(original, quarantine)

    monkeypatch.setattr(
        workspace_runtime,
        "purge_directory_contents",
        real_purge,
    )
    with pytest.raises(
        RuntimeError,
        match="directory carrier object changed during recursive purge",
    ):
        authorities.workspaces.remove_workspace(
            "run-purging-replaced",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert (quarantine / "payload.bin").read_bytes() == b"same-tree"
    assert original.is_dir()


def test_workspace_gc_rejects_live_path_reappearance_after_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-reappeared")
    allocation = authorities.workspaces.allocate_workspace(
        "run-reappeared",
        scope=scope,
        category="study",
    )
    (allocation.path / "payload").write_text("owned", encoding="utf-8")
    gc = _closed_workspace_gc(
        authorities,
        "run-reappeared",
        scope=scope,
        category="study",
    )

    real_purge = workspace_runtime.purge_directory_contents

    def fail_purge(_path, *, expected_generation):
        del expected_generation
        raise OSError("simulated quarantine purge interruption")

    monkeypatch.setattr(workspace_runtime, "purge_directory_contents", fail_purge)
    with pytest.raises(OSError, match="purge interruption"):
        authorities.workspaces.remove_workspace(
            "run-reappeared",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert not allocation.path.exists()
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    quarantined = tuple(quarantine_root.iterdir())
    assert len(quarantined) == 1

    allocation.path.mkdir(parents=True)
    residue = allocation.path / "replacement-residue"
    residue.write_text("new-lifetime", encoding="utf-8")
    monkeypatch.setattr(workspace_runtime, "purge_directory_contents", real_purge)

    with pytest.raises(RuntimeError, match="live path reappeared"):
        authorities.workspaces.remove_workspace(
            "run-reappeared",
            scope=scope,
            category="study",
            gc=gc,
        )

    assert residue.read_text("utf-8") == "new-lifetime"
    assert quarantined[0].exists()


def test_workspace_gc_rejects_split_live_and_quarantine_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_local_directory_authorities(_layout(tmp_path))
    scope = ScopeIdentity(ScopeKind.BRANCH, "branch-split-gc")
    allocation = authorities.workspaces.allocate_workspace(
        "run-split-gc",
        scope=scope,
        category="study",
    )
    (allocation.path / "payload").write_text("owned", encoding="utf-8")
    gc = _closed_workspace_gc(
        authorities,
        "run-split-gc",
        scope=scope,
        category="study",
    )

    real_atomic_replace = workspace_runtime.atomic_replace_bytes
    retirement_writes = 0

    def fail_after_rename(path, data):
        nonlocal retirement_writes
        retirement_writes += 1
        if retirement_writes == 2:
            raise OSError("simulated phase publication loss")
        return real_atomic_replace(path, data)

    monkeypatch.setattr(workspace_runtime, "atomic_replace_bytes", fail_after_rename)
    with pytest.raises(OSError, match="phase publication loss"):
        authorities.workspaces.remove_workspace(
            "run-split-gc",
            scope=scope,
            category="study",
            gc=gc,
        )

    allocation.path.mkdir(parents=True)
    (allocation.path / "foreign").write_text("do-not-delete", encoding="utf-8")
    monkeypatch.setattr(workspace_runtime, "atomic_replace_bytes", real_atomic_replace)

    with pytest.raises(RuntimeError, match="split truth"):
        authorities.workspaces.remove_workspace(
            "run-split-gc",
            scope=scope,
            category="study",
            gc=gc,
        )
    assert (allocation.path / "foreign").read_text("utf-8") == "do-not-delete"

@pytest.mark.parametrize(
    "invalid_age",
    (-1.0, float("nan"), float("inf"), float("-inf"), True),
)
def test_directory_cleanup_rejects_invalid_age_threshold(
    tmp_path: Path,
    invalid_age: float,
) -> None:
    authorities = build_local_directory_authorities(_layout(tmp_path))
    candidate = authorities.layout.root(ManagedDirectoryKind.CACHE) / "keep.bin"
    candidate.write_bytes(b"keep")

    with pytest.raises(ValueError, match="finite non-negative"):
        authorities.cleanup.clean_plan(
            ManagedDirectoryKind.CACHE,
            older_than_seconds=invalid_age,
        )
    assert candidate.read_bytes() == b"keep"

    with pytest.raises(ValueError, match="finite non-negative"):
        authorities.cleanup.clean(
            ManagedDirectoryKind.CACHE,
            older_than_seconds=invalid_age,
        )
    assert candidate.read_bytes() == b"keep"

