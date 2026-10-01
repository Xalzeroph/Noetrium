from __future__ import annotations

from pathlib import Path

import pytest

import noetrium_platform.foundation.kernel.kernel.journal as journal_module
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineIntegrityError,
    MachineStateDelta,
    MachineStateMutation,
    TransitionProposal,
)


def _commit(
    revision: int,
    *,
    previous_commit_id: str | None,
    machine_id: str = "gc-machine",
) -> MachineCommit:
    command = MachineCommand(
        command_id=f"command-{revision}",
        machine_id=machine_id,
        expected_revision=revision - 1,
        kind="step",
        payload={"revision": revision},
        scope=(f"run:{machine_id}",),
    )
    proposal = TransitionProposal(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=revision - 1,
        state_delta=MachineStateDelta((
            MachineStateMutation(("revision",), revision),
        )),
    )
    return MachineCommit(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=revision - 1,
        revision=revision,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        program_digest="f" * 64,
        program_lock_digest="e" * 64,
        state={"revision": revision},
        previous_commit_id=previous_commit_id,
    )


def _closed_closures(
    *,
    evidence: str = "a",
    execution: str = "b",
    recovery: str = "c",
) -> tuple[DurableCarrierReferenceClosure, ...]:
    return (
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.EVIDENCE,
            evidence * 64,
            (),
        ),
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.EXECUTION,
            execution * 64,
            (),
        ),
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.RECOVERY,
            recovery * 64,
            (),
        ),
    )


def _journal(tmp_path: Path) -> tuple[DirectoryMachineJournal, MachineCommit]:
    journal = DirectoryMachineJournal(tmp_path)
    first = _commit(1, previous_commit_id=None)
    assert journal.append(first) == first
    return journal, first


def test_machine_journal_gc_fails_closed_without_complete_reference_closure(
    tmp_path: Path,
) -> None:
    journal, first = _journal(tmp_path)
    partial = journal.assess_gc(
        first.machine_id,
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "d" * 64,
                (),
            ),
        ),
    )
    assert not partial.closure_complete
    assert not partial.eligible
    with pytest.raises(RuntimeError, match="complete execution, evidence, and recovery"):
        journal.purge(first.machine_id, gc=partial)
    assert journal.latest(first.machine_id) == first


@pytest.mark.parametrize(
    ("authority", "reference_id"),
    (
        (DurableCarrierClosureAuthority.EVIDENCE, "evidence-retained"),
        (DurableCarrierClosureAuthority.EXECUTION, "execution-resumable"),
        (DurableCarrierClosureAuthority.RECOVERY, "recovery-retained"),
    ),
)
def test_machine_journal_gc_blocks_each_retained_reference_authority(
    tmp_path: Path,
    authority: DurableCarrierClosureAuthority,
    reference_id: str,
) -> None:
    journal, first = _journal(tmp_path)
    closures = tuple(
        DurableCarrierReferenceClosure(
            current,
            digest * 64,
            (reference_id,) if current is authority else (),
        )
        for current, digest in (
            (DurableCarrierClosureAuthority.EVIDENCE, "4"),
            (DurableCarrierClosureAuthority.EXECUTION, "5"),
            (DurableCarrierClosureAuthority.RECOVERY, "6"),
        )
    )
    gc = journal.assess_gc(first.machine_id, closures=closures)
    assert gc.closure_complete
    assert not gc.eligible
    with pytest.raises(RuntimeError, match="zero retained references"):
        journal.purge(first.machine_id, gc=gc)
    assert journal.latest(first.machine_id) == first


def test_machine_journal_gc_rejects_append_after_assessment(
    tmp_path: Path,
) -> None:
    journal, first = _journal(tmp_path)
    gc = journal.assess_gc(
        first.machine_id,
        closures=_closed_closures(),
    )
    second = _commit(
        2,
        previous_commit_id=first.commit_id,
        machine_id=first.machine_id,
    )
    assert journal.append(second) == second

    with pytest.raises(RuntimeError, match="changed after GC assessment"):
        journal.purge(first.machine_id, gc=gc)
    assert journal.latest(first.machine_id) == second


def test_machine_journal_gc_is_terminal_and_idempotent(
    tmp_path: Path,
) -> None:
    journal, first = _journal(tmp_path)
    closures = _closed_closures()
    gc = journal.assess_gc(first.machine_id, closures=closures)
    assert gc.eligible
    assert journal.purge(first.machine_id, gc=gc)
    assert not tuple((tmp_path / "machines").glob("*.journal"))

    with pytest.raises(MachineIntegrityError, match="retired"):
        journal.latest(first.machine_id)
    with pytest.raises(MachineConflict, match="retired"):
        journal.append(first)

    retry = journal.assess_gc(first.machine_id, closures=closures)
    assert retry == gc
    assert journal.purge(first.machine_id, gc=retry)


def test_machine_journal_gc_recovers_rename_committed_before_phase_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, first = _journal(tmp_path)
    gc = journal.assess_gc(first.machine_id, closures=_closed_closures())
    real_publish = journal_module.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash after journal quarantine rename")
        real_publish(path, payload)

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="after journal quarantine"):
        journal.purge(first.machine_id, gc=gc)

    live = journal._log_path(first.machine_id)
    quarantine = journal._quarantine_path(first.machine_id)
    assert not live.exists()
    assert quarantine.is_file()

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", real_publish)
    assert journal.purge(first.machine_id, gc=gc)
    assert not live.exists()
    assert not quarantine.exists()


def test_machine_journal_gc_rejects_same_content_quarantine_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, first = _journal(tmp_path)
    gc = journal.assess_gc(first.machine_id, closures=_closed_closures())
    real_publish = journal_module.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash after journal quarantine rename")
        real_publish(path, payload)

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="after journal quarantine"):
        journal.purge(first.machine_id, gc=gc)

    quarantine = journal._quarantine_path(first.machine_id)
    original = quarantine.with_name(f"{quarantine.name}.original-generation")
    quarantine.rename(original)
    quarantine.write_bytes(original.read_bytes())

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", real_publish)
    with pytest.raises(RuntimeError, match="filesystem generation changed"):
        journal.purge(first.machine_id, gc=gc)

    assert quarantine.read_bytes() == original.read_bytes()
    assert original.exists()


def test_machine_journal_gc_recovers_unlink_committed_before_terminal_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, first = _journal(tmp_path)
    gc = journal.assess_gc(first.machine_id, closures=_closed_closures())
    real_publish = journal_module.atomic_replace_bytes
    calls = 0

    def fail_third(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated crash after journal physical purge")
        real_publish(path, payload)

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", fail_third)
    with pytest.raises(OSError, match="after journal physical purge"):
        journal.purge(first.machine_id, gc=gc)

    assert not journal._log_path(first.machine_id).exists()
    assert not journal._quarantine_path(first.machine_id).exists()

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", real_publish)
    assert journal.purge(first.machine_id, gc=gc)


def test_machine_journal_gc_retry_rejects_changed_closure_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, first = _journal(tmp_path)
    original = journal.assess_gc(
        first.machine_id,
        closures=_closed_closures(),
    )
    real_publish = journal_module.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash after durable retirement")
        real_publish(path, payload)

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="after durable retirement"):
        journal.purge(first.machine_id, gc=original)

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", real_publish)
    changed = journal.assess_gc(
        first.machine_id,
        closures=_closed_closures(evidence="d", execution="e", recovery="f"),
    )
    with pytest.raises(RuntimeError, match="GC proof changed across retry"):
        journal.purge(first.machine_id, gc=changed)

    assert journal.purge(first.machine_id, gc=original)


def test_machine_journal_gc_rejects_live_reappearance_after_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, first = _journal(tmp_path)
    gc = journal.assess_gc(first.machine_id, closures=_closed_closures())
    real_publish = journal_module.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated phase publication loss")
        real_publish(path, payload)

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="phase publication loss"):
        journal.purge(first.machine_id, gc=gc)

    live = journal._log_path(first.machine_id)
    quarantine = journal._quarantine_path(first.machine_id)
    assert quarantine.is_file()
    live.write_bytes(b"foreign-new-lifetime\n")

    monkeypatch.setattr(journal_module, "atomic_replace_bytes", real_publish)
    with pytest.raises(RuntimeError, match="split live/quarantine truth"):
        journal.purge(first.machine_id, gc=gc)
    assert live.read_bytes() == b"foreign-new-lifetime\n"
    assert quarantine.is_file()
