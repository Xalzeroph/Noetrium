from __future__ import annotations

import json
from pathlib import Path
from multiprocessing import get_context
import subprocess
import sys

import pytest

from noetrium_platform.evidence.artifact.content.api import ArtifactBlobStoreError
from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.foundation.kernel.kernel import (
    CapabilityDescriptor,
    ChildMachineLink,
    ChildMachinePending,
    ChildMachineRecord,
    ChildMachineStatus,
    DirectoryChildMachineSupervisor,
    DirectoryMachineJournal,
    InMemoryChildMachineSupervisor,
    InMemoryPluginRegistry,
    JournalInspectionService,
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineFamilyDescriptor,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineExecutor,
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


def _runtime(root: Path, capabilities=()) -> tuple[MachineExecutor, MachineProgramRef, MachineIdentity]:
    program = _program()
    identity = MachineIdentity("machine-end-state", MachineKind.RUN, "1", "generation-1")
    family = MachineFamilyDescriptor(
        "run.lifecycle.v1", MachineKind.RUN, "1", "run.state.v1",
        command_kinds=("run.start",), replay_level="deterministic",
    )
    runtime = MachineExecutor(
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


def test_run_binding_captures_exact_machine_and_program_identity(tmp_path: Path) -> None:
    program = _program()
    identity = MachineIdentity("binding-machine", MachineKind.RUN, "1", "generation-1")
    runtime = MachineExecutor(
        identity=identity,
        program=program,
        journal=DirectoryMachineJournal(tmp_path),
    )
    binding = RunBinding(
        "machine-abi.v2",
        canonical_digest(identity),
        program.program_digest,
        (("provider", "1"),),
        ("run.state.v1",),
        "environment.v1",
        "policy.v1",
    )
    assert binding.machine_implementation_digest == canonical_digest(runtime.identity)
    assert binding.program_digest == runtime.program.program_digest
    assert binding.binding_digest == canonical_digest({
        "kernel_abi_version": binding.kernel_abi_version,
        "machine_implementation_digest": binding.machine_implementation_digest,
        "program_digest": binding.program_digest,
        "capability_provider_versions": binding.capability_provider_versions,
        "schema_versions": binding.schema_versions,
        "environment_version": binding.environment_version,
        "policy_version": binding.policy_version,
    })


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

def test_nsh_subprocess_is_compiler_verifier_only(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "program.json"
    manifest = tmp_path / "program.nir"
    source.write_text(json.dumps({
        "program_kind": "method",
        "program_version": "1",
        "schema_id": "method.state.v1",
        "code": "return input",
        "dependencies": {},
        "schema": {"type": "object"},
        "data": {},
        "config": {},
    }), encoding="utf-8")
    python = Path(sys.executable)

    compile_result = subprocess.run(
        [str(python), "-m", "noetrium", "nsh", "compile",
         str(source), "-o", str(manifest)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    digest = compile_result.stdout.strip()
    assert len(digest) == 64

    verify_result = subprocess.run(
        [str(python), "-m", "noetrium", "nsh", "verify", str(manifest)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert verify_result.returncode == 0, verify_result.stderr
    assert verify_result.stdout.strip() == digest

    for retired in (
        ("run", "start"),
        ("experiment", "compile"),
        ("evidence", "explain"),
        ("artifact", "list"),
    ):
        result = subprocess.run(
            [str(python), "-m", "noetrium", "nsh", *retired],
            cwd=root, capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert "invalid choice" in result.stderr


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


def test_artifact_blob_store_survives_restart_and_detects_tampering(tmp_path: Path) -> None:
    store = DirectoryArtifactBlobStore(tmp_path)
    ref = store.put(b"evidence-bytes", media_type="text/plain")
    restarted = DirectoryArtifactBlobStore(tmp_path)
    assert restarted.get(ref) == b"evidence-bytes"
    assert restarted.verify(ref)
    blob = tmp_path / ref.content_sha256[:2] / f"{ref.content_sha256}.blob"
    blob.write_bytes(b"tampered")
    assert not restarted.verify(ref)
    with pytest.raises(ArtifactBlobStoreError):
        restarted.get(ref)


def test_directory_child_supervisor_survives_restart(tmp_path: Path) -> None:
    link = ChildMachineLink(
        "parent-durable", "child-durable", canonical_digest("program"),
        "snapshot/child", 1, 3, "result/child", "fail_parent",
    )
    first = DirectoryChildMachineSupervisor(tmp_path)
    first.register(link)
    first.observe(ChildMachineRecord(
        link, ChildMachineStatus.COMPLETED, 3, result_ref="result/child",
    ))
    restarted = DirectoryChildMachineSupervisor(tmp_path)
    assert restarted.join("child-durable").status is ChildMachineStatus.COMPLETED
    assert restarted.list("parent-durable")[0].record_digest


def test_directory_child_records_reject_corruption(tmp_path: Path) -> None:
    link = ChildMachineLink(
        "parent-corrupt", "child-corrupt", canonical_digest("program"),
        "snapshot/child", 1, 3, "result/child", "fail_parent",
    )
    child_root = tmp_path / "children-corrupt"
    child = DirectoryChildMachineSupervisor(child_root)
    child.register(link)
    (child_root / "children.json").write_text("[]x", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        DirectoryChildMachineSupervisor(child_root)
