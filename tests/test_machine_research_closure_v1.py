from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    DeliveryStatus,
    DirectoryMachineInbox,
    DirectoryMachineOutbox,
    InMemoryMachineJournal,
    MachineCommand,
    MachineFamilyDescriptor,
    MachineCut,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineExecutor,
    NIREnvelope,
    ProgramLock,
    TransitionProposal,
    canonical_digest,
)
from noetrium_platform.research.experimentation import DirectoryResearchPackageStore
from noetrium_platform.research.experimentation.record import (
    build_research_package,
    compare_run_records,
    fork_run,
    record_run_cut,
)


def digest(label: str) -> str:
    return canonical_digest({"label": label})


def program() -> MachineProgramRef:
    return MachineProgramRef(
        program_digest=digest("run-program"),
        schema_id="run.v1",
        program_kind="run",
        program_version="1",
        program_lock=ProgramLock(
            code_digest=digest("code"),
            dependency_digest=digest("deps"),
            schema_digest=digest("schema"),
            interpreter_digest=digest("interpreter"),
            data_digest=digest("data"),
            config_digest=digest("config"),
        ),
    )


class Increment:
    def propose(self, command, state):
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta={"count": int(state.state.get("count", 0)) + 1},
        )


def runtime(machine_id: str = "run-1", outbox=None) -> MachineExecutor:
    return MachineExecutor(
        identity=MachineIdentity(
            machine_id=machine_id,
            kind=MachineKind.RUN,
            implementation_version="1",
            generation_id="g1",
        ),
        program=program(),
        journal=InMemoryMachineJournal(),
        outbox=outbox,
        family=MachineFamilyDescriptor(
            family_id="run.v1",
            kind=MachineKind.RUN,
            implementation_version="1",
            state_schema="run.state.v1",
            command_kinds=("increment",),
        ),
    )


def command(machine_id: str, revision: int, command_id: str) -> MachineCommand:
    return MachineCommand(
        command_id=command_id,
        machine_id=machine_id,
        expected_revision=revision,
        kind="increment",
        payload={"amount": 1},
        scope=(f"run:{machine_id}",),
    )


def test_directory_delivery_survives_provider_restart(tmp_path: Path) -> None:
    root = tmp_path / "delivery"
    outbox = DirectoryMachineOutbox(root)
    runtime_one = runtime(outbox=outbox)
    runtime_one.open({"count": 0})
    commit = runtime_one.step(command("run-1", 0, "c1"), Increment())
    pending = outbox.pending()
    assert len(pending) == 0
    assert commit.emitted_commands == ()

    child_runtime = MachineExecutor(
        identity=MachineIdentity(
            machine_id="run-1",
            kind=MachineKind.RUN,
            implementation_version="1",
            generation_id="g1",
        ),
        program=program(),
        journal=runtime_one.journal,
        outbox=outbox,
    )
    child_runtime.open({"count": 0})
    child = child_runtime.step(
        MachineCommand(
            command_id="c2",
            machine_id="run-1",
            expected_revision=1,
            kind="increment",
            payload={"amount": 1},
            scope=("run:run-1",),
        ),
        type("Emit", (), {
            "propose": lambda self, cmd, state: TransitionProposal(
                machine_id=state.machine_id,
                command_id=cmd.command_id,
                base_revision=state.revision,
                state_delta={"count": 2},
                emitted_commands=(command("child", 0, "child-c1"),),
            )
        })(),
    )
    restarted = DirectoryMachineOutbox(root)
    pending = restarted.pending()
    assert len(pending) == 1
    inbox = DirectoryMachineInbox(tmp_path / "inbox")
    assert inbox.accept(pending[0]) is True
    assert DirectoryMachineInbox(tmp_path / "inbox").accept(pending[0]) is False
    receipt = DeliveryReceipt(
        envelope_id=pending[0].envelope_id,
        envelope_digest=pending[0].envelope_digest,
        status=DeliveryStatus.DELIVERED,
        attempt=1,
    )
    restarted.mark(receipt)
    assert DirectoryMachineOutbox(root).pending() == ()
    assert child.revision == 2


def test_nir_round_trip_preserves_command_identity() -> None:
    original = command("run-1", 0, "nir-c1")
    envelope = NIREnvelope.from_command(
        version=1,
        machine_kind=MachineKind.RUN,
        program_digest=program().program_digest,
        command=original,
    )
    assert envelope.to_command() == original


def test_run_cut_builds_record_fork_comparison_and_package(tmp_path: Path) -> None:
    source = runtime()
    source.open({"count": 0})
    source_commit = source.step(command("run-1", 0, "c1"), Increment())
    source_cut = MachineCut.from_commit(source_commit)
    record = record_run_cut(
        source_cut,
        binding_digest=digest("binding-a"),
        status="completed",
        result={"answer": 1},
    )

    target = runtime("run-2")
    target.open(dict(source_commit.state))
    target_commit = target.step(command("run-2", 0, "fork-c1"), Increment())
    target_record = record_run_cut(
        MachineCut.from_commit(target_commit),
        binding_digest=digest("binding-b"),
        status="completed",
        result={"answer": 2},
    )
    fork = fork_run(
        source_run_id=source_cut.machine_id,
        source_commit_id=source_cut.commit_id,
        new_run_id="run-2",
        change_digest=canonical_digest({"temperature": 0.2}),
    )
    comparison = compare_run_records(
        comparison_id="cmp-1",
        runs=(record, target_record),
        evaluator={"metric": "delta"},
        result={"delta": 1},
        status="complete",
    )
    package = build_research_package(
        package_id="package-1",
        definition={"study": "study-1"},
        runs=(record, target_record),
        comparisons=(comparison,),
        forks=(fork,),
        dependencies=(digest("dependency"),),
    )
    store = DirectoryResearchPackageStore(tmp_path / "packages")
    assert store.save(package) == package
    assert store.load("package-1") == package
    assert store.package_ids() == ("package-1",)