from __future__ import annotations

from noetrium_platform.foundation.scope.api import scope_unit
from resource_test_support import build_test_directory_authorities

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
from noetrium_platform.infrastructure.resources.authority.api import (
    TicketState,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayout,
    ManagedDirectoryKind,
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
    workspace_terminal_key,
)
from noetrium_platform.infrastructure.resources.directory.composition import build_local_directory_authorities
from noetrium_platform.foundation.scope.api import (
    NoetriumUnit,
    ScopeKind,
    scope_id,
    scope_key,
    scope_kind,
    scope_to_data,
)


def _closed_workspace_gc(
    authorities,
    workspace_id: str,
    *,
    scope: NoetriumUnit,
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


def _branch_scope(workspaces, branch_id: str):
    authority = workspaces._authority
    experiment = scope_unit(ScopeKind.EXPERIMENT, "workspace-test-experiment:" + branch_id)
    run = scope_unit(ScopeKind.RUN, "workspace-test-run:" + branch_id)
    run_lease = authority.acquire_scope_lease(
        scope=run,
        parent_scope=experiment,
        holder_key=scope_key(run),
        ttl_seconds=300.0,
    )
    branch = scope_unit(ScopeKind.BRANCH, branch_id)
    branch_lease = authority.acquire_scope_lease(
        scope=branch,
        parent_scope=run,
        parent_scope_lease=run_lease,
        holder_key=scope_key(branch),
        ttl_seconds=300.0,
    )
    return branch, branch_lease


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
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-a")
    allocation = authorities.workspaces.allocate_workspace(
        "run-1", scope=scope, scope_lease=scope_lease, category="study", owner="paper-1"
    )
    document = json.loads((allocation.path / ".workspace.json").read_text("utf-8"))
    assert document["schema"] == "resource.workspace-allocation.v2"
    assert "path" not in document["payload"]
    assert document["payload"]["workspace_id"] == "run-1"

    reopened = build_test_directory_authorities(_layout(tmp_path))
    assert reopened.workspaces.list_workspaces(scope=scope, category="study") == (allocation,)


def test_workspace_listing_prunes_nested_non_authority_metadata(tmp_path: Path) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-a")
    allocation = authorities.workspaces.allocate_workspace("run-1", scope=scope, scope_lease=scope_lease, category="study")
    nested = allocation.path / "payload" / "deep" / ".workspace.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("not-json", encoding="utf-8")

    assert authorities.workspaces.list_workspaces(scope=scope, category="study") == (allocation,)


def test_workspace_metadata_tamper_fails_closed(tmp_path: Path) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-a")
    allocation = authorities.workspaces.allocate_workspace("run-1", scope=scope, scope_lease=scope_lease, category="study")
    metadata = allocation.path / ".workspace.json"
    document = json.loads(metadata.read_text("utf-8"))
    document["payload"]["owner"] = "tampered"
    metadata.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(WorkspaceMetadataError) as raised:
        authorities.workspaces.list_workspaces(scope=scope, category="study")
    assert raised.value.code is WorkspaceMetadataFailureCode.DOCUMENT_INTEGRITY


def test_workspace_metadata_cannot_claim_another_identity(tmp_path: Path) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-a")
    allocation = authorities.workspaces.allocate_workspace("run-1", scope=scope, scope_lease=scope_lease, category="study")
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
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-idempotent")
    first = authorities.workspaces.allocate_workspace(
        "run-stable",
        scope=scope, scope_lease=scope_lease,
        category="study",
        owner="paper-1",
        note="stable",
    )
    payload = first.path / "result.bin"
    payload.write_bytes(b"scientific-state")

    second = authorities.workspaces.allocate_workspace(
        "run-stable",
        scope=scope, scope_lease=scope_lease,
        category="study",
        owner="paper-1",
        note="stable",
    )

    assert second == first
    assert payload.read_bytes() == b"scientific-state"
    with pytest.raises(RuntimeError, match="different metadata"):
        authorities.workspaces.allocate_workspace(
            "run-stable",
            scope=scope, scope_lease=scope_lease,
            category="study",
            owner="paper-2",
            note="stable",
        )


def test_workspace_allocation_refuses_unowned_residue(
    tmp_path: Path,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-residue")
    residue = (
        tmp_path
        / "workspaces"
        / scope_kind(scope).value
        / scope_id(scope)
        / "study"
        / "run-residue"
    )
    residue.mkdir(parents=True)
    (residue / "old-output.txt").write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unowned residue"):
        authorities.workspaces.allocate_workspace(
            "run-residue",
            scope=scope, scope_lease=scope_lease,
            category="study",
        )
    assert (residue / "old-output.txt").read_text("utf-8") == "old"


def test_removed_workspace_identity_is_terminal(
    tmp_path: Path,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-retired")
    allocation = authorities.workspaces.allocate_workspace(
        "run-retired",
        scope=scope, scope_lease=scope_lease,
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
            scope=scope, scope_lease=scope_lease,
            category="study",
            owner="paper-1",
        )


def test_workspace_remove_retries_after_terminal_authority_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-remove-retry")
    allocation = manager.allocate_workspace("run-retry", scope=scope, scope_lease=scope_lease, category="study")
    (allocation.path / "payload").write_text("state", encoding="utf-8")
    gc = _closed_workspace_gc(authorities, "run-retry", scope=scope, category="study")
    real_retire = manager._provider.retire
    calls = 0

    def fail_once(reference, ticket):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated workspace provider interruption")
        return real_retire(reference, ticket)

    monkeypatch.setattr(manager._provider, "retire", fail_once)
    with pytest.raises(OSError, match="provider interruption"):
        manager.remove_workspace("run-retry", scope=scope, category="study", gc=gc)

    resource_key = manager._resource_key(scope, "study", "run-retry")
    terminal_key = workspace_terminal_key(resource_key)
    snapshot = manager._authority.snapshot_for_resource_keys(frozenset((resource_key, terminal_key)))
    assert manager._terminal_claim(snapshot, terminal_key) is not None
    retiring = tuple(
        ticket
        for ticket in snapshot.tickets_for(resource_key)
        if ticket_field(ticket, "state") is TicketState.RETIRING
    )
    assert len(retiring) == 1

    assert manager.remove_workspace("run-retry", scope=scope, category="study", gc=gc)
    assert not allocation.path.exists()
    final = manager._authority.snapshot_for_resource_keys(frozenset((resource_key, terminal_key)))
    assert final.current_ticket_for(resource_key) is None
    assert manager._terminal_claim(final, terminal_key) is not None




def test_workspace_gc_fails_closed_without_all_reference_authorities(
    tmp_path: Path,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-gc-blocked")
    allocation = authorities.workspaces.allocate_workspace(
        "run-gc-blocked",
        scope=scope, scope_lease=scope_lease,
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
    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, f"branch-{authority.value}")
    workspace_id = f"run-{authority.value}"
    allocation = authorities.workspaces.allocate_workspace(
        workspace_id,
        scope=scope, scope_lease=scope_lease,
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


def test_workspace_retirement_retry_rejects_changed_gc_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-proof-retry")
    allocation = manager.allocate_workspace("run-proof-retry", scope=scope, scope_lease=scope_lease, category="study")
    gc = _closed_workspace_gc(authorities, "run-proof-retry", scope=scope, category="study")
    real_retire = manager._provider.retire

    def fail_once(reference, ticket):
        monkeypatch.setattr(manager._provider, "retire", real_retire)
        raise OSError("stop after terminal fact")

    monkeypatch.setattr(manager._provider, "retire", fail_once)
    with pytest.raises(OSError, match="terminal fact"):
        manager.remove_workspace("run-proof-retry", scope=scope, category="study", gc=gc)

    changed = manager.assess_workspace_gc(
        "run-proof-retry",
        scope=scope,
        category="study",
        closures=(
            DurableCarrierReferenceClosure(DurableCarrierClosureAuthority.EVIDENCE, "4" * 64, ()),
            DurableCarrierReferenceClosure(DurableCarrierClosureAuthority.EXECUTION, "2" * 64, ()),
            DurableCarrierReferenceClosure(DurableCarrierClosureAuthority.RECOVERY, "3" * 64, ()),
        ),
    )
    with pytest.raises(RuntimeError, match="terminal Authority fact changed"):
        manager.remove_workspace("run-proof-retry", scope=scope, category="study", gc=changed)
    assert allocation.path.exists()





def test_workspace_retirement_recovers_after_quarantine_rename_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-rename-commit")
    allocation = manager.allocate_workspace("run-rename-commit", scope=scope, scope_lease=scope_lease, category="study")
    (allocation.path / "scientific-state.bin").write_bytes(b"durable-state")
    gc = _closed_workspace_gc(authorities, "run-rename-commit", scope=scope, category="study")
    provider_type = type(manager._provider)
    real_purge = provider_type._purge_quarantine
    calls = 0

    def interrupt_after_rename(quarantine, *, ticket_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("crash after quarantine rename")
        return real_purge(quarantine, ticket_id=ticket_id)

    monkeypatch.setattr(provider_type, "_purge_quarantine", staticmethod(interrupt_after_rename))
    with pytest.raises(OSError, match="quarantine rename"):
        manager.remove_workspace("run-rename-commit", scope=scope, category="study", gc=gc)
    assert not allocation.path.exists()
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    assert len(tuple(quarantine_root.iterdir())) == 1

    assert manager.remove_workspace("run-rename-commit", scope=scope, category="study", gc=gc)
    assert tuple(quarantine_root.iterdir()) == ()




def test_workspace_retirement_rejects_quarantine_inode_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-quarantine-replaced")
    allocation = manager.allocate_workspace("run-quarantine-replaced", scope=scope, scope_lease=scope_lease, category="study")
    (allocation.path / "payload").write_text("owned", encoding="utf-8")
    gc = _closed_workspace_gc(authorities, "run-quarantine-replaced", scope=scope, category="study")
    provider_type = type(manager._provider)
    real_purge = provider_type._purge_quarantine

    def stop_after_rename(quarantine, *, ticket_id):
        raise OSError("stop after rename")

    monkeypatch.setattr(provider_type, "_purge_quarantine", staticmethod(stop_after_rename))
    with pytest.raises(OSError, match="after rename"):
        manager.remove_workspace("run-quarantine-replaced", scope=scope, category="study", gc=gc)
    quarantine_root = tmp_path / "workspaces" / ".retired-workspaces"
    (quarantine,) = tuple(quarantine_root.iterdir())
    import shutil
    shutil.rmtree(quarantine)
    quarantine.mkdir()
    monkeypatch.setattr(provider_type, "_purge_quarantine", staticmethod(real_purge))
    with pytest.raises(RuntimeError, match="physical generation changed|physical object changed|generation name"):
        manager.remove_workspace("run-quarantine-replaced", scope=scope, category="study", gc=gc)




def test_workspace_terminal_fact_precedes_physical_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-terminal-first")
    allocation = manager.allocate_workspace("run-terminal-first", scope=scope, scope_lease=scope_lease, category="study")
    gc = _closed_workspace_gc(authorities, "run-terminal-first", scope=scope, category="study")
    resource_key = manager._resource_key(scope, "study", "run-terminal-first")
    terminal_key = workspace_terminal_key(resource_key)

    def prove_terminal_then_fail(reference, ticket):
        snapshot = manager._authority.snapshot_for_resource_keys(frozenset((resource_key, terminal_key)))
        assert manager._terminal_claim(snapshot, terminal_key) is not None
        raise OSError("physical retire deliberately stopped")

    monkeypatch.setattr(manager._provider, "retire", prove_terminal_then_fail)
    with pytest.raises(OSError, match="deliberately stopped"):
        manager.remove_workspace("run-terminal-first", scope=scope, category="study", gc=gc)
    with pytest.raises(RuntimeError, match="retired and cannot be reused"):
        manager.allocate_workspace("run-terminal-first", scope=scope, scope_lease=scope_lease, category="study")
    assert allocation.path.exists()




def test_workspace_gc_retries_partial_recursive_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.resources.directory.runtime.workspaces as workspace_runtime

    authorities = build_test_directory_authorities(_layout(tmp_path))
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-partial-purge")
    allocation = authorities.workspaces.allocate_workspace(
        "run-partial-purge",
        scope=scope, scope_lease=scope_lease,
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


def test_workspace_retirement_recovers_partial_recursive_purge_with_same_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-purge-retry")
    allocation = manager.allocate_workspace("run-purge-retry", scope=scope, scope_lease=scope_lease, category="study")
    nested = allocation.path / "nested"
    nested.mkdir()
    (nested / "payload.bin").write_bytes(b"same-root")
    gc = _closed_workspace_gc(authorities, "run-purge-retry", scope=scope, category="study")
    import shutil
    real_rmtree = shutil.rmtree
    calls = 0

    def partial(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            (path / "payload.bin").unlink()
            raise OSError("partial purge")
        return real_rmtree(path)

    monkeypatch.setattr(shutil, "rmtree", partial)
    with pytest.raises(OSError, match="partial purge"):
        manager.remove_workspace("run-purge-retry", scope=scope, category="study", gc=gc)
    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert manager.remove_workspace("run-purge-retry", scope=scope, category="study", gc=gc)
    assert not allocation.path.exists()




def test_workspace_retirement_rejects_live_path_reappearance_after_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-reappeared")
    allocation = manager.allocate_workspace("run-reappeared", scope=scope, scope_lease=scope_lease, category="study")
    (allocation.path / "payload").write_text("owned", encoding="utf-8")
    gc = _closed_workspace_gc(authorities, "run-reappeared", scope=scope, category="study")
    provider_type = type(manager._provider)

    def stop_after_rename(quarantine, *, ticket_id):
        raise OSError("stop after quarantine")

    monkeypatch.setattr(provider_type, "_purge_quarantine", staticmethod(stop_after_rename))
    with pytest.raises(OSError, match="after quarantine"):
        manager.remove_workspace("run-reappeared", scope=scope, category="study", gc=gc)
    allocation.path.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="both live and quarantine"):
        manager.remove_workspace("run-reappeared", scope=scope, category="study", gc=gc)




def test_workspace_prepared_realization_recovers_without_second_state_machine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
    manager = authorities.workspaces
    scope, scope_lease = _branch_scope(authorities.workspaces, "branch-prepared-recovery")
    provider = manager._provider
    real_realize = provider.realize
    calls = 0

    def realize_then_crash(spec, ticket):
        nonlocal calls
        calls += 1
        identity = real_realize(spec, ticket)
        if calls == 1:
            raise OSError("crash after workspace physical realization")
        return identity

    monkeypatch.setattr(provider, "realize", realize_then_crash)
    with pytest.raises(OSError, match="physical realization"):
        manager.allocate_workspace("run-prepared", scope=scope, scope_lease=scope_lease, category="study")
    path = tmp_path / "workspaces" / scope_kind(scope).value / scope_id(scope) / "study" / "run-prepared"
    assert path.exists()
    resource_key = manager._resource_key(scope, "study", "run-prepared")
    snap = manager._authority.snapshot_for_resource_keys(frozenset((resource_key,)))
    ticket = snap.current_ticket_for(resource_key)
    assert ticket is not None
    assert ticket_field(ticket, "state") is TicketState.PREPARED

    monkeypatch.setattr(provider, "realize", real_realize)
    recovered = manager.allocate_workspace("run-prepared", scope=scope, scope_lease=scope_lease, category="study")
    assert recovered.path == path
    final = manager._authority.snapshot_for_resource_keys(frozenset((resource_key,)))
    bound = final.current_ticket_for(resource_key)
    assert bound is not None
    assert ticket_field(bound, "state") is TicketState.BOUND



@pytest.mark.parametrize(
    "invalid_age",
    (-1.0, float("nan"), float("inf"), float("-inf"), True),
)
def test_directory_cleanup_rejects_invalid_age_threshold(
    tmp_path: Path,
    invalid_age: float,
) -> None:
    authorities = build_test_directory_authorities(_layout(tmp_path))
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

