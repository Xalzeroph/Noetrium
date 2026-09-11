from __future__ import annotations

import json
from pathlib import Path
from multiprocessing import get_context
import subprocess
import sys

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ArtifactRecord,
    CapabilityDescriptor,
    ChildMachineLink,
    ChildMachinePending,
    ChildMachineRecord,
    ChildMachineStatus,
    ContentAddressedStoreError,
    DirectoryContentAddressedStore,
    DirectoryMachineJournal,
    EvidenceBundle,
    InMemoryChildMachineSupervisor,
    InMemoryPluginRegistry,
    InMemoryResourceScheduler,
    ResourceAdmissionError,
    ResourceBudget,
    ResourceCapacity,
    JournalInspectionService,
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineFamilyDescriptor,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineRuntime,
    PluginManifest,
    ProgramLock,
    RunBinding,
    TransitionProposal,
    canonical_digest,
)


def _program() -> MachineProgramRef:
    value = canonical_digest("end-state-program")
    lock = ProgramLock(*(canonical_digest(item) for item in (
        "code", "deps", "schema", "interpreter", "data", "config",
    )))
    return MachineProgramRef(value, "run.state.v1", "run", "1", lock)


def _runtime(root: Path, capabilities=()) -> tuple[MachineRuntime, MachineProgramRef, MachineIdentity]:
    program = _program()
    identity = MachineIdentity("machine-end-state", MachineKind.RUN, "1", "generation-1")
    family = MachineFamilyDescriptor(
        "run.lifecycle.v1", MachineKind.RUN, "1", "run.state.v1",
        command_kinds=("run.start",), replay_level="deterministic",
    )
    runtime = MachineRuntime(
        identity=identity, program=program,
        journal=DirectoryMachineJournal(root), family=family,
        capabilities=capabilities,
    )
    return runtime, program, identity


class _Interpreter:
    def propose(self, command, state):
        child = ChildMachineLink(
            parent_machine_id=command.machine_id,
            child_machine_id="child-1",
            child_program_digest=command.payload_digest,
            child_snapshot_ref="snapshot/child-1",
            child_transition_start=1,
            child_transition_end=2,
            child_result_ref="result/child-1",
            failure_policy="fail_parent",
        )
        return TransitionProposal(
            machine_id=command.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta={"started": True},
            input_refs=("input/start",),
            evidence_refs=("evidence/start",),
            artifact_refs=("artifact/start",),
            child_links=(child,),
        )


def _command(machine_id: str) -> MachineCommand:
    return MachineCommand("command-1", machine_id, 0, "run.start", {"seed": 1})


def test_runtime_persists_full_transition_context_and_replays(tmp_path: Path) -> None:
    runtime, program, identity = _runtime(tmp_path)
    runtime.open({})
    commit = runtime.step(_command(identity.machine_id), _Interpreter())
    assert commit.before_state_digest == canonical_digest({})
    assert commit.input_digest == commit.command_digest
    assert commit.program_digest == program.program_digest
    assert commit.machine_kind == "run"
    assert commit.machine_version == "1"
    assert commit.input_refs == ("input/start",)
    assert commit.evidence_refs == ("evidence/start",)
    assert commit.artifact_refs == ("artifact/start",)
    assert commit.child_links[0].child_machine_id == "child-1"

    restarted, _, _ = _runtime(tmp_path)
    snapshot = restarted.replay()
    assert snapshot.revision == 1
    assert snapshot.state == {"started": True}
    inspection = JournalInspectionService(
        identity=identity, program=program, journal=DirectoryMachineJournal(tmp_path)
    ).inspect(identity.machine_id)
    assert inspection.children[0].failure_policy == "fail_parent"
    assert inspection.evidence_refs == ("evidence/start",)


def test_run_binding_is_verified_at_run_session_boundary(tmp_path: Path) -> None:
    from noetrium_platform.research.experimentation.run.runtime.machine import ResearchRunSession

    program = _program()
    identity = MachineIdentity("binding-machine", MachineKind.RUN, "1", "generation-1")
    runtime = MachineRuntime(
        identity=identity, program=program,
        journal=DirectoryMachineJournal(tmp_path),
    )
    binding = RunBinding(
        "machine-abi.v2", canonical_digest(identity), program.program_digest,
        (("provider", "1"),), ("run.state.v1",), "environment.v1", "policy.v1",
    )
    session = ResearchRunSession(runtime, binding.binding_digest, binding)
    assert session.binding_digest == binding.binding_digest


class _Verifier:
    def verify(self, manifest: PluginManifest) -> bool:
        return manifest.signature_digest == "a" * 64


def test_plugin_manifest_registry_is_permission_neutral_and_signed() -> None:
    manifest = PluginManifest(
        "plugin.run", "1", "kernel.v2", ("run",), ("cap.read",),
        ("run.input.v1",), ("run.output.v1",), ("read",), ("cpu:1",),
        "replayable", "isolated", "a" * 64,
    )
    registry = InMemoryPluginRegistry(_Verifier())
    registry.register(manifest)
    assert registry.get("plugin.run").manifest_digest == manifest.manifest_digest
    with pytest.raises(ValueError):
        registry.register(PluginManifest(
            "plugin.bad", "1", "kernel.v2", ("run",), (), (), (), (), (),
            "replayable", "isolated", "b" * 64,
        ))

def _append_candidate(root: str, command_id: str, queue) -> None:
    journal = DirectoryMachineJournal(Path(root))
    commit = MachineCommit(
        machine_id="cas-machine", command_id=command_id,
        base_revision=0, revision=1,
        proposal_digest=canonical_digest(("proposal", command_id)),
        command_digest=canonical_digest(("command", command_id)),
        state={"command": command_id},
    )
    try:
        journal.append(commit)
    except MachineConflict:
        queue.put("conflict")
    else:
        queue.put("accepted")


def test_directory_journal_cross_process_cas_has_one_winner(tmp_path: Path) -> None:
    context = get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_append_candidate, args=(str(tmp_path), f"command-{index}", queue))
        for index in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    results = [queue.get(timeout=2), queue.get(timeout=2)]
    assert results.count("accepted") == 1
    assert results.count("conflict") == 1
    assert len(DirectoryMachineJournal(tmp_path).commits("cas-machine")) == 1

def test_nsh_subprocess_experiment_and_run_surface(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "experiment.json"
    manifest = tmp_path / "method.nir"
    source.write_text(json.dumps({
        "program_kind": "run",
        "program_version": "1",
        "schema_id": "run.state.v1",
        "code": "return input",
        "dependencies": {},
        "schema": {"type": "object"},
        "data": {},
        "config": {},
    }), encoding="utf-8")
    python = Path(sys.executable)
    compile_result = subprocess.run(
        [str(python), "-m", "noetrium", "nsh", "experiment", "compile",
         str(source), "-o", str(manifest)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    verify_result = subprocess.run(
        [str(python), "-m", "noetrium", "nsh", "verify", str(manifest)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert verify_result.returncode == 0, verify_result.stderr
    start_result = subprocess.run(
        [str(python), "-m", "noetrium", "nsh", "run", "start",
         "--program", str(manifest), "--root", str(tmp_path / "state"),
         "--run-id", "cli-run"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert start_result.returncode == 0, start_result.stderr
    for command in (
        ("run", "inspect", "cli-run"),
        ("run", "replay", "cli-run"),
        ("evidence", "explain", "cli-run"),
        ("artifact", "list", "cli-run"),
    ):
        result = subprocess.run(
            [str(python), "-m", "noetrium", "nsh", *command,
             "--root", str(tmp_path / "state")],
            cwd=root, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, (command, result.stderr)
    descriptor = json.loads(
        (tmp_path / "state" / "runs" / "cli-run" / "run.json").read_text(encoding="utf-8")
    )
    assert descriptor["run_binding"]["program_digest"]


def test_runtime_enforces_granted_capability_scopes(tmp_path: Path) -> None:
    capability = CapabilityDescriptor(
        "run.control", "1", "run.input.v1", "run.output.v1", "control",
        ("run:machine-end-state",), {}, "idempotent", "required",
    )
    runtime, _, identity = _runtime(tmp_path, (capability,))
    runtime.open({})
    with pytest.raises(MachineConflict, match="scope"):
        runtime.step(
            MachineCommand(
                "denied", identity.machine_id, 0, "run.start", {},
                ("run:other-machine",),
            ),
            _Interpreter(),
        )

def test_resource_scheduler_enforces_capacity_and_releases() -> None:
    scheduler = InMemoryResourceScheduler(ResourceCapacity(10, 100, 1, 5))
    budget = ResourceBudget(8, 80, 1, 3)
    lease = scheduler.acquire("owner-a", budget)
    assert scheduler.acquire("owner-a", budget) == lease
    with pytest.raises(ResourceAdmissionError):
        scheduler.acquire("owner-b", ResourceBudget(3, 1, 0, 1))
    scheduler.release(lease)
    assert scheduler.available() == ResourceCapacity(10, 100, 1, 5)
    with pytest.raises(ResourceAdmissionError):
        scheduler.release(lease)


def test_child_supervisor_requires_terminal_join() -> None:
    link = ChildMachineLink(
        "parent-1", "child-supervised", canonical_digest("child-program"),
        "snapshot/child", 0, 2, None, "fail_parent",
    )
    supervisor = InMemoryChildMachineSupervisor()
    created = supervisor.register(link)
    assert created.status is ChildMachineStatus.CREATED
    with pytest.raises(ChildMachinePending):
        supervisor.join("child-supervised")
    supervisor.observe(ChildMachineRecord(link, ChildMachineStatus.RUNNING, 1))
    completed = supervisor.observe(ChildMachineRecord(
        link, ChildMachineStatus.COMPLETED, 2, result_ref="result/child",
    ))
    assert supervisor.join("child-supervised") == completed
    assert supervisor.list("parent-1") == (completed,)


def test_content_addressed_evidence_and_artifact_survive_restart(tmp_path: Path) -> None:
    store = DirectoryContentAddressedStore(tmp_path)
    ref = store.put(b"evidence-bytes", kind="evidence", media_type="text/plain",
                    metadata={"source": "test"})
    bundle = store.save_bundle(EvidenceBundle(
        "evidence-1", "claim", (ref,), {"run_id": "run-1"},
    ))
    artifact = store.save_artifact(ArtifactRecord(
        "artifact-1", ref, "run-1", "result",
    ))
    restarted = DirectoryContentAddressedStore(tmp_path)
    assert restarted.get(ref) == b"evidence-bytes"
    assert restarted.load_bundle("evidence-1") == bundle
    assert restarted.load_artifact("artifact-1") == artifact
    assert restarted.verify(ref)
    (tmp_path / "blobs" / f"{ref.content_digest}.bin").write_bytes(b"tampered")
    assert not restarted.verify(ref)
    with pytest.raises(ContentAddressedStoreError):
        restarted.get(ref)

def test_runtime_reservation_is_released_after_interpreter_failure(tmp_path: Path) -> None:
    scheduler = InMemoryResourceScheduler(ResourceCapacity(1, 1, 1, 1))
    runtime, _, identity = _runtime(tmp_path)
    runtime = MachineRuntime(
        identity=identity, program=runtime.program, journal=runtime.journal,
        family=runtime.family, resource_scheduler=scheduler,
        resource_budget=ResourceBudget(1, 1, 1, 1),
    )
    runtime.open({})
    with pytest.raises(ValueError):
        runtime.step(
            MachineCommand("bad-resource", identity.machine_id, 0, "run.start", {}),
            type("RejectingInterpreter", (), {
                "propose": lambda self, command, state: (_ for _ in ()).throw(
                    ValueError("interpreter failed")
                )
            })(),
        )
    assert scheduler.active() == ()
