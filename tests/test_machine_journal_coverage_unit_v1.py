"""Journal coverage certifies only immutable accepted facts, not physical effects."""
from dataclasses import replace
import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineCommand,
    MachineExecutor,
    MachineIdentity,
    MachineIntegrityError,
    MachineStateDelta,
    ExecutableUnitRef,
    UnitExecutionLock,
    JournalInspectionService,
    TransitionProposal,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.inspection import MachineHistoryInspection


def _runtime():
    identity = MachineIdentity("coverage-run", "1", "generation-1")
    unit = ExecutableUnitRef(
        unit_digest=canonical_digest({"unit": "coverage"}),
        state_schema="coverage.state.v1",
        domain="coverage",
        version="1",
        execution_lock=UnitExecutionLock(
            **{
                key: canonical_digest({key: 1})
                for key in (
                    "code_digest", "dependency_digest", "schema_digest",
                    "unit_machine_digest", "data_digest", "config_digest"
                )
            }
        ),
    )
    journal = InMemoryMachineJournal()
    runtime = MachineExecutor(identity=identity, unit=unit, journal=journal)
    return identity, unit, journal, runtime


class _Proposer:
    def propose(self, command, snapshot):
        return TransitionProposal(
            machine_id=command.machine_id,
            command_id=command.command_id,
            base_revision=snapshot.revision,
            state_delta=MachineStateDelta.set(
                ("counter",), snapshot.state.get("counter", 0) + 1
            ),
            event_payloads=({"type": "counter_changed", "count": snapshot.revision + 1},),
            evidence_refs=(f"observation-{snapshot.revision + 1}",),
        )


def test_coverage_is_derived_from_committed_history_without_claiming_physical_truth():
    identity, unit, journal, runtime = _runtime()
    runtime.open({"counter": 0})
    proposer = _Proposer()
    for index in range(3):
        runtime.step(
            MachineCommand(f"command-{index}", identity.machine_id, index, "increment"),
            proposer,
        )
    inspection = JournalInspectionService(
        identity=identity, unit=unit, journal=journal,
    ).inspect(identity.machine_id)
    coverage = inspection.journal_coverage_unit()
    assert coverage.has_schema("machine.journal-coverage.v1")
    assert coverage.attribute("revision") == 3
    assert coverage.attribute("event_count") == 3
    assert coverage.attribute("evidence_reference_count") == 3
    assert coverage.attribute("external_effects_verified") is False
    assert coverage.attribute("referenced_artifacts_verified") is False
    assert coverage.attribute("head_commit_id") == inspection.commit_ids[-1]
    assert inspection.journal_coverage_unit().unit_digest == coverage.unit_digest


def test_inspection_rejects_an_uncommitted_gap_or_divergent_cut():
    identity, unit, journal, runtime = _runtime()
    runtime.open()
    proposer = _Proposer()
    for index in range(2):
        runtime.step(
            MachineCommand(f"c-{index}", identity.machine_id, index, "increment"),
            proposer,
        )
    valid = JournalInspectionService(
        identity=identity, unit=unit, journal=journal
    ).inspect(identity.machine_id)
    with pytest.raises(MachineIntegrityError):
        replace(valid, commit_ids=("0" * 64,) + valid.commit_ids[1:])
    with pytest.raises(MachineIntegrityError):
        replace(valid, transitions=(valid.transitions[-1],))
    with pytest.raises(MachineIntegrityError):
        replace(valid, unit=replace(unit, unit_digest="a" * 64))


def test_outbox_failure_after_durable_commit_is_recovered_without_duplicate(tmp_path):
    from noetrium_platform.foundation.kernel.kernel import (
        DirectoryMachineJournal, DirectoryMachineOutbox,
    )

    class FailFirstOutbox(DirectoryMachineOutbox):
        def __init__(self, root):
            super().__init__(root)
            self.fail = True

        def enqueue(self, commit):
            if self.fail:
                self.fail = False
                raise OSError("injected crash after durable machine commit")
            return super().enqueue(commit)

    class EmittingProposer:
        def propose(self, command, snapshot):
            return TransitionProposal(
                machine_id=command.machine_id,
                command_id=command.command_id,
                base_revision=snapshot.revision,
                state_delta=MachineStateDelta.set(("done",), True),
                event_payloads=({"type": "child_scheduled"},),
                emitted_commands=(
                    MachineCommand("child-1", "child-machine", 0, "work"),
                ),
            )

    identity, unit, _unused, _ = _runtime()
    journal = DirectoryMachineJournal(tmp_path / "journal")
    outbox = FailFirstOutbox(tmp_path / "delivery")
    first = MachineExecutor(
        identity=identity, unit=unit, journal=journal, outbox=outbox
    )
    first.open()
    with pytest.raises(OSError, match="injected crash"):
        first.step(MachineCommand("parent-1", identity.machine_id, 0, "start"), EmittingProposer())
    assert len(journal.commits(identity.machine_id)) == 1

    # Recreate both authorities as if the process crashed. The accepted commit
    # must remain fact even when the derived delivery projection did not write.
    reopened_journal = DirectoryMachineJournal(tmp_path / "journal")
    reopened_outbox = DirectoryMachineOutbox(tmp_path / "delivery")
    second = MachineExecutor(
        identity=identity, unit=unit, journal=reopened_journal, outbox=reopened_outbox
    )
    assert second.open().revision == 1
    assert len(reopened_outbox.pending()) == 1
    assert reopened_outbox.pending()[0].command.command_id == "child-1"
    assert len(second.reconcile_outbox()) == 1
    assert len(reopened_outbox.pending()) == 1


def test_mutated_durable_event_cannot_be_reclassified_as_covered(tmp_path):
    from noetrium_platform.foundation.kernel.kernel import DirectoryMachineJournal

    identity, unit, _unused, _ = _runtime()
    journal = DirectoryMachineJournal(tmp_path / "journal")
    runtime = MachineExecutor(identity=identity, unit=unit, journal=journal)
    runtime.open()
    runtime.step(
        MachineCommand("record", identity.machine_id, 0, "increment"),
        _Proposer(),
    )
    journal_dir = tmp_path / "journal" / "machines"
    matching = [
        f for f in journal_dir.iterdir() if f.is_file()
        and b"counter_changed" in f.read_bytes()
    ]
    assert len(matching) == 1
    p = matching[0]
    raw = p.read_bytes()
    p.write_bytes(raw.replace(b"counter_changed", b"counter_damaged"))
    tampered = DirectoryMachineJournal(tmp_path / "journal")
    with pytest.raises((MachineIntegrityError, ValueError)):
        JournalInspectionService(
            identity=identity, unit=unit, journal=tampered
        ).inspect(identity.machine_id)


def test_mutable_delivery_projection_never_changes_the_accepted_cut_proof():
    identity, unit, journal, runtime = _runtime()
    runtime.open()
    runtime.step(
        MachineCommand("c-1", identity.machine_id, 0, "increment"),
        _Proposer(),
    )
    baseline = JournalInspectionService(
        identity=identity, unit=unit, journal=journal,
    ).inspect(identity.machine_id)
    # A delivery can become pending/complete without changing an accepted
    # MachineCommit. The read-only *inspection* changes, but the proof cannot.
    pending = replace(baseline, pending_command_ids=("child-delayed",))
    assert baseline.inspection_digest != pending.inspection_digest
    assert (
        baseline.journal_coverage_unit().unit_digest
        == pending.journal_coverage_unit().unit_digest
    )


def test_committed_events_are_stable_lossless_units_for_future_metrics():
    from noetrium_platform.foundation.kernel.unit_codec import (
        encode_unit, decode_unit,
    )

    identity, unit, journal, runtime = _runtime()
    runtime.open()
    proposer = _Proposer()
    for index in range(2):
        runtime.step(
            MachineCommand(f"e-{index}", identity.machine_id, index, "increment"),
            proposer,
        )
    inspection = JournalInspectionService(
        identity=identity, unit=unit, journal=journal,
    ).inspect(identity.machine_id)
    event_units = inspection.accepted_event_units()
    assert len(event_units) == 2
    assert all(x.has_schema("machine.accepted-event.v1") for x in event_units)
    assert tuple(e.attribute("payload")["count"] for e in event_units) == (1, 2)
    assert event_units[0].attribute("source_commit_id") == inspection.commit_ids[0]
    assert event_units[1].attribute("previous_commit_id") == inspection.commit_ids[0]
    assert all(decode_unit(encode_unit(e)) == e for e in event_units)

    # Different downstream functions can derive new metrics after the run,
    # without mutating either scientific history or the frozen Unit.
    total = len(event_units)
    positive = sum(int(e.attribute("payload")["count"] > 0) for e in event_units)
    assert (total, positive) == (2, 2)
    assert (
        tuple(e.unit_digest for e in inspection.accepted_event_units())
        == tuple(e.unit_digest for e in event_units)
    )


def test_existing_metric_engine_derives_custom_metrics_from_accepted_journal():
    from noetrium_platform.composition.research_scientific_analysis import (
        machine_journal_metric_records,
    )
    from noetrium_platform.research.experimentation.projection import MetricEngine
    from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
        metric_definition_unit,
    )
    from noetrium_platform.foundation.kernel.record import record_provenance

    identity, unit, journal, runtime = _runtime()
    runtime.open()
    proposer = _Proposer()
    for index in range(3):
        runtime.step(
            MachineCommand(f"m-{index}", identity.machine_id, index, "increment"),
            proposer,
        )
    inspection = JournalInspectionService(
        identity=identity, unit=unit, journal=journal
    ).inspect(identity.machine_id)
    assert tuple(inspection.iter_accepted_event_units()) == inspection.accepted_event_units()
    records = machine_journal_metric_records(inspection)
    assert len(records) == 3
    assert all(record_provenance(row)["authority"] == "machine-journal" for row in records)
    count = metric_definition_unit(
        "journal-event-count", aggregation="count",
        record_types=("machine.accepted-event",),
    )
    max_revision = metric_definition_unit(
        "journal-maximum-revision", aggregation="max",
        record_types=("machine.accepted-event",),
        value_path=("revision",),
    )
    result = MetricEngine.evaluate(records, (count, max_revision))
    values = {row.metric_id: row.value for row in result.values}
    assert values == {"journal-event-count": 3, "journal-maximum-revision": 3.0}
    assert MetricEngine.evaluate(records, (count, max_revision)).report_digest == result.report_digest


def test_metric_coverage_unit_exposes_omitted_values_and_predicates():
    from noetrium_platform.composition.research_scientific_analysis import (
        machine_journal_metric_records,
    )
    from noetrium_platform.research.experimentation.projection import MetricEngine
    from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
        metric_definition_unit, metric_predicate_unit,
    )

    identity, unit, journal, runtime = _runtime()
    runtime.open()
    proposer = _Proposer()
    for i in range(2):
        runtime.step(MachineCommand(f"coverage-{i}", identity.machine_id, i, "inc"), proposer)
    history = JournalInspectionService(identity=identity, unit=unit, journal=journal).inspect(identity.machine_id)
    records = machine_journal_metric_records(history)
    base = {"record_types": ("machine.accepted-event",)}
    complete = metric_definition_unit(
        "max-revision", aggregation="max", value_path=("revision",), **base
    )
    missing_value = metric_definition_unit(
        "missing-value", aggregation="sum", value_path=("event", "not_recorded"),
        missing="skip", **base
    )
    missing_predicate = metric_definition_unit(
        "missing-predicate", aggregation="count",
        predicates=(metric_predicate_unit(("event", "missing"), True),), **base
    )
    first = MetricEngine.coverage_unit(records, (complete,))
    assert first.parameters["complete_relative_to_cut"] is True
    assert first.parameters["external_truth_verified"] is False
    partial = MetricEngine.coverage_unit(records, (missing_value, missing_predicate))
    assert partial.parameters["complete_relative_to_cut"] is False
    rows = {x["metric_id"]: x for x in partial.parameters["per_metric"]}
    assert rows["missing-value"]["missing_value_count"] == 2
    assert rows["missing-predicate"]["missing_predicate_count"] == 2
    assert partial.unit_digest == MetricEngine.coverage_unit(
        records, (missing_value, missing_predicate)
    ).unit_digest
