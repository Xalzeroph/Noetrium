"""nsh command line and SDK facade for canonical program compilation."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Sequence

from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    JournalInspectionService,
    MachineCommand,
    MachineFamilyDescriptor,
    MachineIdentity,
    MachineKind,
    MachineRuntime,
    NshCompiler,
    ProgramSource,
    RunBinding,
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
    thaw_json,
)
from noetrium_platform.research.execution.machines.reference import RunLifecycleInterpreter


def _read_object(path: Path) -> dict[str, object]:
    value = strict_json_loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def compile_file(
    source_path: str | Path,
    output_path: str | Path,
    *,
    interpreter_id: str = "noetrium.machine",
    interpreter_version: str = "1",
) -> dict[str, object]:
    compiler = NshCompiler(
        interpreter_id=interpreter_id,
        interpreter_version=interpreter_version,
    )
    compiled = compiler.compile(ProgramSource.from_mapping(_read_object(Path(source_path))))
    manifest = compiled.manifest()
    Path(output_path).write_bytes(canonical_bytes(manifest, indent=2))
    return manifest


def verify_file(
    manifest_path: str | Path,
    *,
    interpreter_id: str = "noetrium.machine",
    interpreter_version: str = "1",
) -> str:
    compiler = NshCompiler(
        interpreter_id=interpreter_id,
        interpreter_version=interpreter_version,
    )
    program = compiler.verify_manifest(_read_object(Path(manifest_path)))
    return program.program_digest


def _emit(value: object) -> None:
    print(json.dumps(thaw_json(value), sort_keys=True, separators=(",", ":")))


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical_bytes(value, indent=2))
    os.replace(temporary, path)


def _run_descriptor(root: Path, run_id: str) -> dict[str, object]:
    descriptor = _read_object(root / "runs" / run_id / "run.json")
    if descriptor.get("run_id") != run_id:
        raise ValueError("run descriptor identity mismatch")
    return descriptor


def _run_runtime(root: Path, run_id: str) -> tuple[MachineRuntime, object, object]:
    descriptor = _run_descriptor(root, run_id)
    program = NshCompiler(
        interpreter_id="noetrium.machine",
        interpreter_version="1",
    ).verify_manifest(descriptor["program_manifest"])
    identity = MachineIdentity(
        run_id, MachineKind.RUN,
        str(descriptor["implementation_version"]),
        str(descriptor["generation_id"]),
    )
    binding_data = descriptor.get("run_binding")
    if not isinstance(binding_data, dict):
        raise ValueError("run descriptor missing run_binding")
    binding = RunBinding(
        kernel_abi_version=str(binding_data["kernel_abi_version"]),
        machine_implementation_digest=str(binding_data["machine_implementation_digest"]),
        program_digest=str(binding_data["program_digest"]),
        capability_provider_versions=tuple(tuple(item) for item in binding_data["capability_provider_versions"]),
        schema_versions=tuple(str(item) for item in binding_data["schema_versions"]),
        environment_version=str(binding_data["environment_version"]),
        policy_version=str(binding_data["policy_version"]),
    )
    if binding.binding_digest != binding_data.get("binding_digest"):
        raise ValueError("run binding digest mismatch")
    if binding.program_digest != program.program_digest:
        raise ValueError("run binding program mismatch")
    if binding.machine_implementation_digest != canonical_digest(identity):
        raise ValueError("run binding machine mismatch")
    family = MachineFamilyDescriptor(
        family_id="run.lifecycle.v1",
        kind=MachineKind.RUN,
        implementation_version=identity.implementation_version,
        state_schema=program.schema_id,
        replay_level="replayable",
        command_kinds=("run.start", "run.pause", "run.resume", "run.complete", "run.fail"),
    )
    journal = DirectoryMachineJournal(root / "runs" / run_id / "journal")
    return MachineRuntime(
        identity=identity, program=program, journal=journal, family=family
    ), program, identity


def _run_start(args: argparse.Namespace) -> int:
    root = Path(args.root)
    manifest = _read_object(Path(args.program))
    program = NshCompiler(
        interpreter_id="noetrium.machine",
        interpreter_version="1",
    ).verify_manifest(manifest)
    run_id = args.run_id or uuid.uuid4().hex
    run_dir = root / "runs" / run_id
    if (run_dir / "run.json").exists():
        raise ValueError(f"run already exists: {run_id}")
    identity = MachineIdentity(run_id, MachineKind.RUN, program.program_version, uuid.uuid4().hex)
    binding = RunBinding(
        kernel_abi_version="machine-abi.v2",
        machine_implementation_digest=canonical_digest(identity),
        program_digest=program.program_digest,
        capability_provider_versions=(),
        schema_versions=(program.schema_id,),
        environment_version="environment.v1",
        policy_version="policy.v1",
    )
    runtime = MachineRuntime(
        identity=identity,
        program=program,
        journal=DirectoryMachineJournal(run_dir / "journal"),
        family=MachineFamilyDescriptor(
            family_id="run.lifecycle.v1",
            kind=MachineKind.RUN,
            implementation_version=identity.implementation_version,
            state_schema=program.schema_id,
            replay_level="replayable",
            command_kinds=("run.start", "run.pause", "run.resume", "run.complete", "run.fail"),
        ),
    )
    runtime.open({"status": "created", "seed": args.seed})
    runtime.step(
        MachineCommand(
            command_id=uuid.uuid4().hex,
            machine_id=run_id,
            expected_revision=0,
            kind="run.start",
            payload={"seed": args.seed},
            scope=(f"run:{run_id}",),
        ),
        RunLifecycleInterpreter(),
    )
    _atomic_json(run_dir / "run.json", {
        "schema": "noetrium.nsh.run.v1",
        "run_id": run_id,
        "generation_id": identity.generation_id,
        "implementation_version": identity.implementation_version,
        "program_manifest": manifest,
        "run_binding": {
            "kernel_abi_version": binding.kernel_abi_version,
            "machine_implementation_digest": binding.machine_implementation_digest,
            "program_digest": binding.program_digest,
            "capability_provider_versions": binding.capability_provider_versions,
            "schema_versions": binding.schema_versions,
            "environment_version": binding.environment_version,
            "policy_version": binding.policy_version,
            "binding_digest": binding.binding_digest,
        },
        "seed": args.seed,
    })
    print(run_id)
    return 0


def _run_change(args: argparse.Namespace) -> int:
    runtime, _, identity = _run_runtime(Path(args.root), args.run_id)
    snapshot = runtime.open()
    commit = runtime.step(
        MachineCommand(
            command_id=uuid.uuid4().hex,
            machine_id=args.run_id,
            expected_revision=snapshot.revision,
            kind=f"run.{args.action}",
            payload={},
            scope=(f"run:{args.run_id}",),
        ),
        RunLifecycleInterpreter(),
    )
    _emit({"run_id": args.run_id, "revision": commit.revision, "status": args.action})
    return 0


def _run_inspect(args: argparse.Namespace) -> int:
    root = Path(args.root)
    runtime, program, identity = _run_runtime(root, args.run_id)
    runtime.open()
    view = JournalInspectionService(
        identity=identity,
        program=program,
        journal=runtime.journal,
        outbox=runtime.outbox,
    ).inspect(args.run_id)
    _emit({
        "run_id": args.run_id,
        "revision": view.revision,
        "commit_ids": view.commit_ids,
        "effect_intent_refs": view.effect_intent_refs,
        "evidence_refs": view.evidence_refs,
        "artifact_refs": view.artifact_refs,
        "pending_command_ids": view.pending_command_ids,
        "inspection_digest": view.inspection_digest,
    })
    return 0


def _run_replay(args: argparse.Namespace) -> int:
    runtime, _, _ = _run_runtime(Path(args.root), args.run_id)
    runtime.open()
    revision = None
    if args.from_ref is not None:
        history = runtime.journal.commits(args.run_id)
        matches = [item.revision for item in history if item.commit_id == args.from_ref]
        revision = int(args.from_ref) if args.from_ref.isdigit() else (matches[0] if matches else None)
        if revision is None:
            raise ValueError("replay boundary is not a known revision or commit")
    snapshot = runtime.replay(revision)
    _emit({"run_id": args.run_id, "revision": snapshot.revision, "state": snapshot.state})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nsh")
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile", help="compile a canonical nsh source")
    compile_parser.add_argument("source")
    compile_parser.add_argument("-o", "--output", required=True)
    compile_parser.add_argument("--interpreter-id", default="noetrium.machine")
    compile_parser.add_argument("--interpreter-version", default="1")
    verify_parser = sub.add_parser("verify", help="verify a compiled program manifest")
    verify_parser.add_argument("manifest")
    verify_parser.add_argument("--interpreter-id", default="noetrium.machine")
    verify_parser.add_argument("--interpreter-version", default="1")
    experiment = sub.add_parser("experiment")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    experiment_compile = experiment_sub.add_parser("compile")
    experiment_compile.add_argument("source")
    experiment_compile.add_argument("-o", "--output", required=True)
    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    start = run_sub.add_parser("start")
    start.add_argument("--program", required=True)
    start.add_argument("--root", default=".noetrium")
    start.add_argument("--run-id")
    start.add_argument("--seed", type=int, default=0)
    for action in ("pause", "resume", "complete", "fail"):
        command = run_sub.add_parser(action)
        command.add_argument("run_id")
        command.add_argument("--root", default=".noetrium")
        command.set_defaults(action=action)
    inspect = run_sub.add_parser("inspect")
    inspect.add_argument("run_id")
    inspect.add_argument("--root", default=".noetrium")
    replay = run_sub.add_parser("replay")
    replay.add_argument("run_id")
    replay.add_argument("--from", dest="from_ref")
    replay.add_argument("--root", default=".noetrium")
    evidence = sub.add_parser("evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_explain = evidence_sub.add_parser("explain")
    evidence_explain.add_argument("run_id")
    evidence_explain.add_argument("--root", default=".noetrium")
    artifact = sub.add_parser("artifact")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_sub.add_parser("list")
    artifact_list.add_argument("run_id")
    artifact_list.add_argument("--root", default=".noetrium")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"compile", "experiment"}:
        if args.command == "experiment":
            args.command = "compile"
        manifest = compile_file(args.source, args.output)
        print(manifest["program_digest"])
        return 0
    if args.command == "verify":
        print(verify_file(args.manifest))
        return 0
    if args.command == "run":
        if args.run_command == "start":
            return _run_start(args)
        if args.run_command in {"pause", "resume", "complete", "fail"}:
            return _run_change(args)
        if args.run_command == "inspect":
            return _run_inspect(args)
        return _run_replay(args)
    run_id = args.run_id
    runtime, program, identity = _run_runtime(Path(args.root), run_id)
    runtime.open()
    view = JournalInspectionService(
        identity=identity, program=program, journal=runtime.journal
    ).inspect(run_id)
    key = "evidence_refs" if args.command == "evidence" else "artifact_refs"
    _emit({"run_id": run_id, key: getattr(view, key)})
    return 0


__all__ = ["build_parser", "compile_file", "main", "verify_file"]
