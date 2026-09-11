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
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineRuntime,
    NIREnvelope,
    ProgramLock,
    TransitionProposal,
    canonical_digest,
)
from noetrium_platform.research.experimentation import DirectoryResearchPackageStore
from noetrium_platform.research.experimentation.run.runtime import ResearchRunSession


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


def runtime(machine_id: str = "run-1", outbox=None) -> MachineRuntime:
    return MachineRuntime(
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

    child_runtime = MachineRuntime(
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


def test_run_session_builds_record_fork_comparison_and_package(tmp_path: Path) -> None:
    source = ResearchRunSession(runtime(), digest("binding-a"))
    target = ResearchRunSession(runtime("run-2"), digest("binding-b"))
    source.open({"count": 0})
    source.step(command("run-1", 0, "c1"), Increment())
    record = source.record(status="completed", result={"answer": 1})
    fork = source.fork(target=target, change={"temperature": 0.2})
    target.step(command("run-2", 0, "fork-c1"), Increment())
    target_record = target.record(status="completed", result={"answer": 2})
    comparison = ResearchRunSession.compare(
        comparison_id="cmp-1",
        runs=(record, target_record),
        evaluator={"metric": "delta"},
        result={"delta": 1},
        status="complete",
    )
    package = ResearchRunSession.package(
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