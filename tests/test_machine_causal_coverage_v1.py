"""Cross-Machine cut verification, with no inferred provider effects."""
from dataclasses import replace

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ChildMachineLink, InMemoryMachineJournal, JournalInspectionService,
    MachineCommand, MachineCut, MachineExecutor, MachineIdentity,
    MachineIntegrityError, MachineStateDelta, TransitionProposal,
)
from noetrium_platform.foundation.kernel.kernel.causal_coverage import (
    verify_machine_causal_closure,
)
from tests.test_machine_journal_coverage_unit_v1 import _runtime, _Proposer


class _LinkProposer:
    def __init__(self, link):
        self.link = link

    def propose(self, command, snapshot):
        return TransitionProposal(
            machine_id=command.machine_id, command_id=command.command_id,
            base_revision=snapshot.revision,
            state_delta=MachineStateDelta.set(("children",), 1),
            child_links=(self.link,),
            event_payloads=({"type": "child_verified"},),
        )


def _linked_machine(*, damaged_cut=False):
    parent, unit, journal, executor = _runtime()
    child_id = MachineIdentity("child-machine", "1", "generation-1")
    child = MachineExecutor(identity=child_id, unit=unit, journal=journal)
    child.open()
    commit = child.step(
        MachineCommand("child-step", child_id.machine_id, 0, "work"),
        _Proposer(),
    )
    cut = MachineCut.from_commit(commit)
    snapshot = f"machine:{child_id.machine_id}:cut:1:{cut.cut_digest}"
    if damaged_cut:
        snapshot = f"machine:{child_id.machine_id}:cut:1:{'0' * 64}"
    link = ChildMachineLink(
        parent_machine_id=parent.machine_id,
        child_machine_id=child_id.machine_id,
        child_unit_digest=unit.unit_digest,
        child_execution_lock_digest=unit.execution_lock.lock_digest,
        child_snapshot_ref=snapshot,
        child_transition_start=0,
        child_transition_end=1,
        child_result_ref=None,
        failure_policy="propagate",
    )
    executor.open()
    executor.step(
        MachineCommand("parent-step", parent.machine_id, 0, "execute"),
        _LinkProposer(link),
    )
    root = JournalInspectionService(
        identity=parent, unit=unit, journal=journal,
    ).inspect(parent.machine_id)
    return root, journal


def test_recursive_causal_coverage_validates_real_child_cut():
    root, journal = _linked_machine()
    proof = verify_machine_causal_closure(root, journal)
    assert proof.has_schema("machine.causal-coverage.v1")
    assert proof.attribute("verified_child_link_count") == 1
    assert proof.attribute("verified_child_machine_count") == 1
    assert proof.attribute("external_effects_verified") is False
    assert proof.attribute("referenced_artifacts_verified") is False
    assert verify_machine_causal_closure(root, journal).unit_digest == proof.unit_digest


def test_forged_child_cut_fails_closed():
    root, journal = _linked_machine(damaged_cut=True)
    with pytest.raises(MachineIntegrityError, match="snapshot cut"):
        verify_machine_causal_closure(root, journal)


def test_missing_child_history_cannot_be_covered():
    root, journal = _linked_machine()
    parent_only = InMemoryMachineJournal()
    for commit in root.transitions:
        parent_only.append(commit)
    with pytest.raises(MachineIntegrityError, match="child Machine cut is missing"):
        verify_machine_causal_closure(root, parent_only)


def test_child_lock_drift_cannot_be_covered():
    root, journal = _linked_machine()
    child = root.children[0]
    wrong = replace(child, child_execution_lock_digest="a" * 64)
    # The parent commit digest binds the original reference, so use an
    # independent forged inspection to prove the projection rejects drift.
    with pytest.raises(MachineIntegrityError):
        replace(root, children=(wrong,))


def test_transitive_child_cut_closure_verifies_grandchild():
    parent_id, unit, journal, parent = _runtime()
    grand_id = MachineIdentity("grandchild", "1", "generation-1")
    grand = MachineExecutor(identity=grand_id, unit=unit, journal=journal)
    grand.open()
    grand_commit = grand.step(
        MachineCommand("grand-cmd", "grandchild", 0, "work"), _Proposer()
    )

    def link(owner, source):
        cut = MachineCut.from_commit(source)
        return ChildMachineLink(
            parent_machine_id=owner,
            child_machine_id=cut.machine_id,
            child_unit_digest=cut.unit_digest,
            child_execution_lock_digest=cut.execution_lock_digest,
            child_snapshot_ref=f"machine:{cut.machine_id}:cut:{cut.revision}:{cut.cut_digest}",
            child_transition_start=0,
            child_transition_end=cut.revision,
            child_result_ref=None,
            failure_policy="propagate",
        )

    middle_id = MachineIdentity("middle", "1", "generation-1")
    middle = MachineExecutor(identity=middle_id, unit=unit, journal=journal)
    middle.open()
    middle_commit = middle.step(
        MachineCommand("middle-cmd", "middle", 0, "work"),
        _LinkProposer(link("middle", grand_commit)),
    )
    parent.open()
    parent.step(
        MachineCommand("parent-cmd", parent_id.machine_id, 0, "work"),
        _LinkProposer(link(parent_id.machine_id, middle_commit)),
    )
    root = JournalInspectionService(
        identity=parent_id, unit=unit, journal=journal
    ).inspect(parent_id.machine_id)
    proof = verify_machine_causal_closure(root, journal)
    assert proof.attribute("verified_child_link_count") == 2
    assert proof.attribute("verified_child_machine_count") == 2


def test_newer_child_commits_do_not_change_frozen_parent_cut():
    root, journal = _linked_machine()
    first = verify_machine_causal_closure(root, journal)
    child_id = MachineIdentity("child-machine", "1", "generation-1")
    reopened = MachineExecutor(identity=child_id, unit=root.unit, journal=journal)
    assert reopened.open().revision == 1
    reopened.step(
        MachineCommand("second-child-step", "child-machine", 1, "work"),
        _Proposer(),
    )
    assert verify_machine_causal_closure(root, journal).unit_digest == first.unit_digest
    from noetrium_platform.composition.research_scientific_analysis import machine_causal_metric_records
    assert len(machine_causal_metric_records(root, journal)) == 2


def test_metric_engine_sees_verified_child_events_without_duplicate_records():
    from noetrium_platform.composition.research_scientific_analysis import (
        machine_causal_metric_records,
    )
    from noetrium_platform.research.experimentation.projection import MetricEngine
    from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
        metric_definition_unit,
    )

    root, journal = _linked_machine()
    records = machine_causal_metric_records(root, journal)
    assert len(records) == 2
    by_machine = metric_definition_unit(
        "by-machine", aggregation="count",
        record_types=("machine.accepted-event",),
        group_by=(("dimensions", "machine_id"),),
    )
    result = MetricEngine.evaluate(records, (by_machine,))
    assert {tuple(value.group_key): value.value for value in result.values} == {
        ("coverage-run",): 1,
        ("child-machine",): 1,
    }
    assert MetricEngine.coverage_unit(
        records, (by_machine,)
    ).parameters["complete_relative_to_cut"] is True
