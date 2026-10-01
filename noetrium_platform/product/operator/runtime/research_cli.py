from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import sys

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.product.operator.api import ProjectCreateRequest
from noetrium_platform.product.operator.api.json_rendering import render_json
from noetrium_platform.product.operator.api.project_experience import ProjectFacade
from noetrium_platform.product.research_os import (
    ResearchControlAction,
    ResearchExecutionTarget,
)


ResearchCliDelegate = Callable[[list[str] | None], int]
ProjectResearchOSLoader = Callable[..., object]
_EXPECTED_ERRORS = (
    KeyError,
    ValueError,
    FileNotFoundError,
    OSError,
    RuntimeError,
    TypeError,
    json.JSONDecodeError,
)


def _emit(value, *, stream=None) -> None:
    print(render_json(value), file=stream or sys.stdout)


def _add_lifecycle_command(
    subparsers,
    action: ResearchControlAction,
    help_text: str,
) -> None:
    parser = subparsers.add_parser(action.value, help=help_text)
    parser.set_defaults(action=action, route="project")
    parser.add_argument(
        "target",
        nargs="?",
        help="logical Research OS execution identity; defaults to project identity",
    )
    parser.add_argument(
        "--project",
        dest="project_root",
        type=Path,
        default=Path("."),
        help="downstream project root; defaults to current directory",
    )
    parser.add_argument(
        "--program",
        help="optional program id for node-scoped control",
    )
    parser.add_argument(
        "--node",
        help="optional node id for node-scoped control",
    )
    payload = parser.add_mutually_exclusive_group()
    payload.add_argument("--payload", help="inline JSON payload")
    payload.add_argument(
        "--payload-file",
        type=Path,
        help="UTF-8 JSON payload file",
    )


def _add_project_commands(subparsers) -> None:
    project = subparsers.add_parser(
        "project",
        help="create and validate downstream projects",
    )
    project_subparsers = project.add_subparsers(
        dest="project_command",
        required=True,
    )

    create = project_subparsers.add_parser(
        "create",
        help="create a deterministic downstream scaffold",
    )
    create.add_argument("project_id")
    create.add_argument("destination", type=Path, nargs="?")
    create.add_argument("--version", default="0.1.0")

    sync = project_subparsers.add_parser(
        "sync",
        help="regenerate platform-owned shell without touching user scientific core",
    )
    sync.add_argument(
        "--project",
        dest="project_root",
        type=Path,
        default=Path("."),
    )

    doctor = project_subparsers.add_parser(
        "doctor",
        help="validate project/platform/provider readiness",
    )
    doctor.add_argument(
        "--project",
        dest="project_root",
        type=Path,
        default=Path("."),
    )

    test = project_subparsers.add_parser(
        "test",
        help="run generated downstream conformance tests",
    )
    test.add_argument(
        "--project",
        dest="project_root",
        type=Path,
        default=Path("."),
    )


def build_research_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noetrium",
        description="Canonical Noetrium Research OS control surface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    help_text = {
        ResearchControlAction.RUN: "run the working research revision",
        ResearchControlAction.INSPECT: "inspect the active durable research cut",
        ResearchControlAction.PAUSE: "pause graph or node admission",
        ResearchControlAction.DRAIN: "drain graph or node admission",
        ResearchControlAction.INTERRUPT: "interrupt graph or node execution",
        ResearchControlAction.RESUME: "resume graph or node admission",
        ResearchControlAction.RETRY: "retry one definitively failed node boundary",
        ResearchControlAction.CANCEL: "cancel graph or node/subgraph execution",
        ResearchControlAction.CHECKPOINT: "checkpoint exact lower-machine state",
        ResearchControlAction.RECONCILE: "reconcile one uncertain node from lower proof",
        ResearchControlAction.MIGRATE: "migrate the active cut to the working revision",
    }
    for action in ResearchControlAction:
        _add_lifecycle_command(subparsers, action, help_text[action])
    subparsers.add_parser("diagnose", help="forensic/read-side operator tools")
    subparsers.add_parser("manage", help="platform management and deployment tools")
    retire = subparsers.add_parser(
        "retire",
        help="terminally retire the host Runtime Fabric after a research campaign",
    )
    retire.add_argument(
        "--project",
        dest="project_root",
        type=Path,
        default=Path("."),
        help="downstream project root; defaults to current directory",
    )
    _add_project_commands(subparsers)
    return parser


def _load_payload(args: argparse.Namespace):
    if args.payload_file is not None:
        return json.loads(args.payload_file.read_text(encoding="utf-8"))
    if args.payload is not None:
        return json.loads(args.payload)
    return None


def _execution_target(args: argparse.Namespace, loaded) -> ResearchExecutionTarget:
    if (args.program is None) != (args.node is None):
        raise ValueError("--program and --node must be supplied together")
    execution_id = args.target or loaded.default_execution_id
    revision = loaded.revision
    if args.action not in {
        ResearchControlAction.RUN,
        ResearchControlAction.MIGRATE,
    }:
        revision = loaded.active_revision or loaded.revision
    target = ResearchExecutionTarget(execution_id, revision)
    if args.program is not None:
        target = target.for_node(args.program, args.node)
    return target


def _run_project_lifecycle(
    args: argparse.Namespace,
    project_research_os_loader: ProjectResearchOSLoader,
) -> int:
    revision_intent = (
        "working"
        if args.action in {ResearchControlAction.RUN, ResearchControlAction.MIGRATE}
        else "active"
    )
    loaded = project_research_os_loader(
        args.project_root,
        revision_intent=revision_intent,
    )
    try:
        target = _execution_target(args, loaded)
        operation = getattr(loaded.research_os, args.action.value)
        receipt = operation(target, _load_payload(args))
        _emit({"ok": True, "command": args.command, "result": receipt})
        return 0
    finally:
        loaded.close()


def _run_project_retirement(
    args: argparse.Namespace,
    project_research_os_loader: ProjectResearchOSLoader,
) -> int:
    loaded = project_research_os_loader(args.project_root)
    try:
        loaded.retire_runtime_fabric()
        _emit(
            {
                "ok": True,
                "command": "retire",
                "result": {
                    "project": str(args.project_root),
                    "runtime_fabric": "retired",
                },
            }
        )
        return 0
    finally:
        loaded.close()


def _run_project(
    args: argparse.Namespace,
    project_experience: ProjectFacade,
) -> int:
    if args.project_command == "create":
        destination = args.destination or Path(args.project_id)
        receipt = project_experience.create(
            args.project_id,
            args.version,
            destination,
        )
        _emit({"ok": True, "command": "project create", "result": receipt})
        return 0
    if args.project_command == "sync":
        receipt = project_experience.sync(args.project_root)
        _emit({"ok": True, "command": "project sync", "result": receipt})
        return 0
    if args.project_command == "doctor":
        report = project_experience.doctor(args.project_root)
        _emit(
            {"ok": report.ready, "command": "project doctor", "result": report},
            stream=None if report.ready else sys.stderr,
        )
        return 0 if report.ready else 4
    if args.project_command == "test":
        receipt = project_experience.test(args.project_root)
        _emit(
            {"ok": receipt.passed, "command": "project test", "result": receipt},
            stream=None if receipt.passed else sys.stderr,
        )
        return 0 if receipt.passed else 4
    raise ValueError(f"unsupported project command: {args.project_command}")


def run_research_cli(
    argv: list[str] | None,
    *,
    diagnose_main: ResearchCliDelegate,
    manage_main: ResearchCliDelegate,
    project_experience: ProjectFacade,
    project_research_os_loader: ProjectResearchOSLoader,
) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "diagnose":
        return diagnose_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "manage":
        return manage_main(raw_argv[1:])
    args = build_research_parser().parse_args(raw_argv)
    try:
        if args.command == "project":
            return _run_project(args, project_experience)
        if args.command == "retire":
            return _run_project_retirement(
                args,
                project_research_os_loader,
            )
        return _run_project_lifecycle(args, project_research_os_loader)
    except _EXPECTED_ERRORS as exc:
        descriptor = describe_exception(exc)
        _emit(
            {
                "ok": False,
                "command": args.command,
                "error_type": descriptor.error_type,
                "error": descriptor.safe_message,
                "error_digest": descriptor.error_digest,
            },
            stream=sys.stderr,
        )
        return 2


__all__ = [
    "ProjectResearchOSLoader",
    "ResearchCliDelegate",
    "build_research_parser",
    "run_research_cli",
]
