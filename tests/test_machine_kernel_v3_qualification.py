from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import subprocess
import sys

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    InMemoryMachineAuthority,
    InMemoryMachineJournal,
    MachineCommand,
    MachineConflict,
    MachineIdentity,
    MachineKind,
    MachineLeaseBusy,
    MachineLeaseLost,
    MachineProgramRef,
    MachineRuntime,
    MachineSnapshot,
    NIREnvelope,
    ProgramLock,
    TransitionProposal,
    WorkerAdmission,
    WorkerAdmissionError,
    WorkerAdmissionPolicy,
    WorkerAuthenticationError,
    WorkerAuthenticator,
    WorkerReply,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.authority import (
    DirectoryMachineAuthority,
    MachineAuthorityError,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntent,
    EffectIntentConflict,
    EffectIntentPhase,
    EffectReconciliationDisposition,
    EffectReconciliationProof,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    EffectReconciliationService,
    InMemoryEffectIntentJournal,
    SQLiteEffectIntentJournal,
)

ROOT = Path(__file__).resolve().parents[1]


def _program() -> MachineProgramRef:
    lock = ProgramLock(*(canonical_digest(value) for value in (
        "code", "dependencies", "schema", "interpreter", "data", "config",
    )))
    return MachineProgramRef(canonical_digest("program"), "state.v1", "test", "1", lock)


def _intent(request_digest: str = "a" * 64) -> EffectIntent:
    return EffectIntent.build(
        request_id="request-v3",
        request_digest=request_digest,
        operation_id="operation-v3",
        provider_component=ComponentIdentity("provider.v3", "fake", "1", "1", "g1"),
        context=ExecutionContext("run-v3", "trace-v3", "span-v3", lifetime_id="life-v3"),
        intent_namespace="v3-test",
    )


def _effect(intent: EffectIntent, certainty: EffectCertainty) -> EffectReceipt:
    return EffectReceipt(
        "effect-v3", intent.request_digest, EffectClass.RECONCILABLE,
        certainty, "provider-v3", False,
    )
def _authority_race_child(directory: str, owner: str, start, results) -> None:
    start.wait()
    try:
        lease = DirectoryMachineAuthority(Path(directory)).acquire(
            "race-machine", owner, ttl_seconds=30.0, now=100.0
        )
    except MachineLeaseBusy:
        results.put("busy")
    except BaseException as exc:
        results.put(f"error:{type(exc).__name__}:{exc}")
    else:
        results.put(f"acquired:{lease.owner_id}:{lease.epoch}")


def test_directory_authority_cross_process_acquire_has_one_winner(tmp_path) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_authority_race_child,
            args=(str(tmp_path / "authority"), owner, start, results),
        )
        for owner in ("owner-a", "owner-b")
    ]
    for process in processes:
        process.start()
    start.set()
    rows = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
    assert all(process.exitcode == 0 for process in processes)
    assert sorted(row.startswith("acquired:") for row in rows) == [False, True]
    assert sum(row == "busy" for row in rows) == 1


def test_directory_authority_old_epoch_is_fenced(tmp_path) -> None:
    authority_path = tmp_path / "authority"
    first = DirectoryMachineAuthority(authority_path)
    old = first.acquire("fenced-machine", "owner-a", ttl_seconds=1, now=0.0)
    successor = DirectoryMachineAuthority(authority_path).acquire(
        "fenced-machine", "owner-b", ttl_seconds=30, now=2.0
    )
    assert successor.epoch == old.epoch + 1
    with pytest.raises(MachineLeaseLost):
        first.assert_held(old, now=2.0)
    with pytest.raises(MachineLeaseLost):
        first.release(old)


@pytest.mark.parametrize("payload", [b"{", b"{}"])
def test_directory_authority_rejects_corrupt_lease_document(tmp_path, payload) -> None:
    authority = DirectoryMachineAuthority(tmp_path / "authority")
    lease = authority.acquire("corrupt-machine", "owner-a", now=10.0)
    authority._path(lease.machine_id).write_bytes(payload)
    with pytest.raises(MachineAuthorityError):
        DirectoryMachineAuthority(authority.directory).assert_held(lease, now=10.5)


def test_directory_authority_rejects_tampered_digest_and_noncanonical_json(tmp_path) -> None:
    authority = DirectoryMachineAuthority(tmp_path / "authority")
    lease = authority.acquire("tampered-machine", "owner-a", now=10.0)
    path = authority._path(lease.machine_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["lease_digest"] = "0" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(MachineAuthorityError, match="digest mismatch|canonical"):
        DirectoryMachineAuthority(authority.directory).assert_held(lease, now=10.5)
class _Provider:
    def __init__(self, proof: EffectReconciliationProof):
        self.proof = proof
        self.calls = 0

    def reconcile(self, intent: EffectIntent, record):
        self.calls += 1
        return self.proof


def test_effect_unknown_stays_unknown_and_uncommitted() -> None:
    intent = _intent()
    journal = InMemoryEffectIntentJournal()
    journal.prepare(intent)
    provider = _Provider(EffectReconciliationProof(
        intent.request_id, EffectReconciliationDisposition.UNKNOWN, None,
    ))
    result = EffectReconciliationService(journal, provider).reconcile(intent.intent_id)
    assert result.disposition is EffectReconciliationDisposition.UNKNOWN
    assert result.changed is False
    assert result.record.phase is EffectIntentPhase.PREPARED
    assert provider.calls == 1


def test_effect_reconciliation_rejects_wrong_request_digest() -> None:
    intent = _intent()
    journal = InMemoryEffectIntentJournal()
    journal.prepare(intent)
    wrong = _effect(_intent("b" * 64), EffectCertainty.EFFECT_CONFIRMED)
    provider = _Provider(EffectReconciliationProof(
        intent.request_id, EffectReconciliationDisposition.APPLIED, wrong,
    ))
    with pytest.raises(ValueError, match="request digest mismatch"):
        EffectReconciliationService(journal, provider).reconcile(intent.intent_id)
    assert journal.load(intent.intent_id).phase is EffectIntentPhase.PREPARED


def test_effect_not_applied_requires_authoritative_no_effect() -> None:
    intent = _intent()
    journal = InMemoryEffectIntentJournal()
    journal.prepare(intent)
    provider = _Provider(EffectReconciliationProof(
        intent.request_id, EffectReconciliationDisposition.NOT_APPLIED,
        _effect(intent, EffectCertainty.EFFECT_CONFIRMED),
    ))
    with pytest.raises(EffectIntentConflict, match="NO_EFFECT"):
        EffectReconciliationService(journal, provider).reconcile(intent.intent_id)
    assert journal.load(intent.intent_id).phase is EffectIntentPhase.PREPARED
def test_effect_reconciliation_is_idempotent_after_restart(tmp_path) -> None:
    intent = _intent()
    path = tmp_path / "effects.sqlite"
    first_journal = SQLiteEffectIntentJournal(path)
    first_journal.prepare(intent)
    first_provider = _Provider(EffectReconciliationProof(
        intent.request_id, EffectReconciliationDisposition.APPLIED,
        _effect(intent, EffectCertainty.EFFECT_CONFIRMED),
    ))
    first = EffectReconciliationService(first_journal, first_provider).reconcile(
        intent.intent_id
    )
    assert first.record.phase is EffectIntentPhase.RECONCILED
    assert first.changed is True

    class _MustNotCall:
        def reconcile(self, intent, record):
            raise AssertionError("terminal reconciliation must not call provider")

    reopened = SQLiteEffectIntentJournal(path)
    second = EffectReconciliationService(reopened, _MustNotCall()).reconcile(
        intent.intent_id
    )
    assert second.disposition is EffectReconciliationDisposition.APPLIED
    assert second.changed is False
    assert second.record == reopened.load(intent.intent_id)


def _worker_setup():
    identity = MachineIdentity("worker-machine", MachineKind.RUN, "1", "g1")
    program = _program()
    authenticator = WorkerAuthenticator(b"worker-secret")
    policy = WorkerAdmissionPolicy(
        identity.machine_id, identity.kind, program.program_digest, "worker-v3",
        ("research.read",),
    )
    admission = WorkerAdmission(
        identity=identity, program=program, policy=policy,
        authenticator=authenticator,
    )
    return identity, program, authenticator, admission


def _command(*, scope=("research.read",), revision=0, command_id="worker-cmd"):
    return MachineCommand(
        command_id, "worker-machine", revision, "run.start", {"value": 1}, scope,
    )


def _state(identity, program):
    return MachineSnapshot(identity.machine_id, 0, program, {}, None)


def test_worker_replay_is_idempotent_and_does_not_reinvoke_worker() -> None:
    identity, program, authenticator, admission = _worker_setup()
    calls = []
    class Worker:
        def propose(self, envelope, state):
            calls.append(envelope.envelope_digest)
            proposal = TransitionProposal(
                envelope.machine_id, envelope.command_id, state.revision, {"ok": True},
            )
            return WorkerReply(
                proposal,
                authenticator.sign(envelope.envelope_digest, proposal.proposal_digest),
            )
    runtime = MachineRuntime(
        identity=identity, program=program, journal=InMemoryMachineJournal()
    )
    runtime.open({})
    from noetrium_platform.foundation.kernel.kernel import AuthenticatedWorkerInterpreter
    interpreter = AuthenticatedWorkerInterpreter(
        identity=identity, program=program, admission=admission, worker=Worker()
    )
    command = _command()
    first = runtime.step(command, interpreter)
    second = runtime.step(command, interpreter)
    assert first == second
    assert len(calls) == 1
def test_worker_rejects_bad_signature_without_commit() -> None:
    identity, program, authenticator, admission = _worker_setup()
    class Worker:
        def propose(self, envelope, state):
            proposal = TransitionProposal(
                envelope.machine_id, envelope.command_id, state.revision, {"bad": True},
            )
            return WorkerReply(proposal, "not-a-valid-signature")
    runtime = MachineRuntime(
        identity=identity, program=program, journal=InMemoryMachineJournal()
    )
    runtime.open({})
    from noetrium_platform.foundation.kernel.kernel import AuthenticatedWorkerInterpreter
    interpreter = AuthenticatedWorkerInterpreter(
        identity=identity, program=program, admission=admission, worker=Worker()
    )
    with pytest.raises(WorkerAuthenticationError):
        runtime.step(_command(), interpreter)
    assert runtime.inspect().revision == 0


def test_worker_rejects_unauthorized_scope() -> None:
    identity, program, authenticator, admission = _worker_setup()
    envelope = NIREnvelope.from_command(
        version=1, machine_kind=identity.kind, program_digest=program.program_digest,
        command=_command(scope=("admin.write",)),
    )
    proposal = TransitionProposal(
        envelope.machine_id, envelope.command_id, 0, {},
    )
    reply = WorkerReply(
        proposal, authenticator.sign(envelope.envelope_digest, proposal.proposal_digest)
    )
    with pytest.raises(WorkerAdmissionError, match="scope"):
        admission.admit(envelope, _state(identity, program), reply)


def test_worker_rejects_wrong_program_digest() -> None:
    identity, program, authenticator, admission = _worker_setup()
    envelope = NIREnvelope.from_command(
        version=1, machine_kind=identity.kind, program_digest=canonical_digest("wrong"),
        command=_command(),
    )
    proposal = TransitionProposal(envelope.machine_id, envelope.command_id, 0, {})
    reply = WorkerReply(
        proposal, authenticator.sign(envelope.envelope_digest, proposal.proposal_digest)
    )
    with pytest.raises(WorkerAdmissionError, match="program digest"):
        admission.admit(envelope, _state(identity, program), reply)


def test_worker_rejects_expired_stale_proposal() -> None:
    identity, program, authenticator, admission = _worker_setup()
    envelope = NIREnvelope.from_command(
        version=1, machine_kind=identity.kind, program_digest=program.program_digest,
        command=_command(),
    )
    proposal = TransitionProposal(envelope.machine_id, envelope.command_id, 1, {})
    reply = WorkerReply(
        proposal, authenticator.sign(envelope.envelope_digest, proposal.proposal_digest)
    )
    with pytest.raises(MachineConflict, match="stale"):
        admission.admit(envelope, _state(identity, program), reply)
def test_nsh_cli_compile_and_verify_are_real_subprocesses(tmp_path) -> None:
    source_path = tmp_path / "program.json"
    manifest_path = tmp_path / "program.manifest.json"
    source_path.write_text(json.dumps({
        "program_kind": "method",
        "program_version": "1",
        "schema_id": "method.state.v1",
        "code": "return input",
        "dependencies": {"stdlib": "1"},
        "schema": {"type": "object"},
        "data": {"fixture": 1},
        "config": {"strict": True},
    }), encoding="utf-8")
    compiled = subprocess.run(
        [sys.executable, "-m", "noetrium", "nsh", "compile",
         str(source_path), "-o", str(manifest_path)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    digest = compiled.stdout.strip()
    assert len(digest) == 64
    assert manifest_path.exists()

    verified = subprocess.run(
        [sys.executable, "-m", "noetrium", "nsh", "verify", str(manifest_path)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert verified.stdout.strip() == digest
