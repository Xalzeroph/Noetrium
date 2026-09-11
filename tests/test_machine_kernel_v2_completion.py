from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    AuthenticatedWorkerInterpreter,
    InMemoryMachineAuthority,
    InMemoryMachineJournal,
    MachineCommand,
    MachineIdentity,
    MachineKind,
    MachineLeaseLost,
    MachineProgramRef,
    MachineRuntime,
    MachineSnapshot,
    MachineConformanceHarness,
    NshCompiler,
    ProgramLock,
    ProgramSource,
    TransitionProposal,
    WorkerAdmission,
    WorkerAdmissionPolicy,
    WorkerAuthenticator,
    WorkerReply,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.authority import DirectoryMachineAuthority
from noetrium_platform.foundation.kernel.kernel.nir import NIREnvelope


def _program() -> MachineProgramRef:
    digest = canonical_digest("same-program")
    lock = ProgramLock(*(canonical_digest(value) for value in (
        "code", "dependencies", "schema", "interpreter", "data", "config",
    )))
    return MachineProgramRef(digest, "test.state.v1", "test", "1", lock)


class _Interpreter:
    def propose(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal:
        return TransitionProposal(
            state.machine_id,
            command.command_id,
            state.revision,
            {"last": command.kind},
            event_payloads=({"kind": command.kind},),
        )


def _command(machine_id: str, revision: int, command_id: str) -> MachineCommand:
    return MachineCommand(command_id, machine_id, revision, "tick", {"value": revision})


def test_machine_authority_fences_expired_owner_before_commit() -> None:
    now = [100.0]
    authority = InMemoryMachineAuthority(clock=lambda: now[0])
    lease_a = authority.acquire("m1", "worker-a", ttl_seconds=5)
    runtime = MachineRuntime(
        identity=MachineIdentity("m1", MachineKind.RUN, "1", "generation-1"),
        program=_program(),
        journal=InMemoryMachineJournal(),
        authority=authority,
        authority_lease=lease_a,
    )
    runtime.open({})
    runtime.step(_command("m1", 0, "c1"), _Interpreter())
    now[0] = 106.0
    authority.acquire("m1", "worker-b", ttl_seconds=5)
    with pytest.raises(MachineLeaseLost):
        runtime.step(_command("m1", 1, "c2"), _Interpreter())


def test_directory_machine_authority_preserves_epoch_across_restart(tmp_path) -> None:
    path = tmp_path / "authority"
    first = DirectoryMachineAuthority(path)
    lease = first.acquire("m2", "owner-a", now=10.0)
    first.release(lease)
    second = DirectoryMachineAuthority(path)
    next_lease = second.acquire("m2", "owner-b", now=20.0)
    assert next_lease.epoch == lease.epoch + 1


def test_nsh_compiler_binds_complete_program_lock() -> None:
    compiler = NshCompiler(interpreter_id="test.interpreter", interpreter_version="7")
    compiled = compiler.compile(ProgramSource(
        "method", "1", "method.state.v1", "return input",
        dependencies={"stdlib": "1"},
        schema={"type": "object"},
        data={"fixture": 1},
        config={"strict": True},
    ))
    manifest = compiled.manifest()
    restored = compiler.verify_manifest(manifest)
    assert restored == compiled.program
    assert restored.program_lock.lock_digest == manifest["program_lock"]["lock_digest"]


def test_authenticated_worker_candidate_is_admitted_and_committed() -> None:
    program = _program()
    identity = MachineIdentity("m3", MachineKind.RUN, "1", "generation-1")
    authenticator = WorkerAuthenticator(b"test-secret")
    policy = WorkerAdmissionPolicy(
        "m3", MachineKind.RUN, program.program_digest, "worker-1", ("research.read",)
    )
    authority = WorkerAdmission(
        identity=identity, program=program, policy=policy, authenticator=authenticator
    )

    class Worker:
        def propose(self, envelope: NIREnvelope, state: MachineSnapshot) -> WorkerReply:
            proposal = TransitionProposal(
                envelope.machine_id, envelope.command_id, state.revision, {"worker": True}
            )
            return WorkerReply(
                proposal,
                authenticator.sign(envelope.envelope_digest, proposal.proposal_digest),
            )

    runtime = MachineRuntime(
        identity=identity, program=program, journal=InMemoryMachineJournal()
    )
    runtime.open({})
    interpreter = AuthenticatedWorkerInterpreter(
        identity=identity, program=program, admission=authority, worker=Worker()
    )
    commit = runtime.step(
        MachineCommand("c1", "m3", 0, "tick", {}, ("research.read",)), interpreter
    )
    assert commit.state["worker"] is True


def test_golden_history_conformance_compares_facts() -> None:
    def build():
        runtime = MachineRuntime(
            identity=MachineIdentity("m4", MachineKind.RUN, "1", "generation-1"),
            program=_program(),
            journal=InMemoryMachineJournal(),
        )
        return runtime, _Interpreter()

    report = MachineConformanceHarness().compare(
        builders={"reference-a": build, "reference-b": build},
        commands=(_command("m4", 0, "c1"), _command("m4", 1, "c2")),
    )
    assert report.common_history_digest
    assert len(report.runs[0].projections) == 2
