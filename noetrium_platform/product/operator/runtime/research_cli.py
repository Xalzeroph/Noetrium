from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path
import sys

from noetrium_platform.product.api import decode_research_project_blueprint
from noetrium_platform.product.operator.api import (
    ProjectCreateRequest, ResearchAction, ResearchFacade, ResearchOperationFailure,
)
from noetrium_platform.product.operator.api.project_experience import ProjectFacade
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from noetrium_platform.product.operator.api.json_rendering import render_json


ResearchCliDelegate = Callable[[list[str] | None], int]
ProjectApplicationLoader = Callable[..., object]
_EXPECTED_ERRORS = (KeyError, ValueError, FileNotFoundError, OSError, RuntimeError, TypeError, json.JSONDecodeError)



def _emit(value, *, stream=None) -> None:
    print(
        render_json(value),
        file=stream or sys.stdout,
    )


def _add_lifecycle_command(subparsers, action: ResearchAction, help_text: str) -> None:
    parser = subparsers.add_parser(action.value, help=help_text)
    parser.set_defaults(action=action, route="project")
    parser.add_argument("target", nargs="?", help="application-owned target identity")
    parser.add_argument(
        "--project", dest="project_root", type=Path, default=Path("."),
        help="downstream project root; defaults to current directory",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="optional project-owned runtime configuration path",
    )
    payload = parser.add_mutually_exclusive_group()
    payload.add_argument("--payload", help="inline JSON payload")
    payload.add_argument("--payload-file", type=Path, help="UTF-8 JSON payload file")


def _add_project_commands(subparsers) -> None:
    project = subparsers.add_parser("project", help="create and validate downstream projects")
    project_subparsers = project.add_subparsers(dest="project_command", required=True)

    create = project_subparsers.add_parser("create", help="create a deterministic downstream scaffold")
    create.add_argument("project_id")
    create.add_argument("destination", type=Path, nargs="?")
    create.add_argument("--version", default="0.1.0")
    create.add_argument(
        "--blueprint",
        type=Path,
        help="typed Research OS blueprint JSON; defaults to canonical fill-in scaffold",
    )

    doctor = project_subparsers.add_parser("doctor", help="validate project/platform/provider readiness")
    doctor.add_argument("--project", dest="project_root", type=Path, default=Path("."))

    test = project_subparsers.add_parser("test", help="run generated downstream conformance tests")
    test.add_argument("--project", dest="project_root", type=Path, default=Path("."))

def build_research_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noetrium",
        description="Canonical Noetrium product control surface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_lifecycle_command(subparsers, ResearchAction.RUN, "start one application-owned run")
    _add_lifecycle_command(subparsers, ResearchAction.INSPECT, "inspect exact application state")
    _add_lifecycle_command(subparsers, ResearchAction.STOP, "stop one application-owned run")
    _add_lifecycle_command(subparsers, ResearchAction.RESUME, "resume one application-owned run")
    _add_lifecycle_command(
        subparsers,
        ResearchAction.RECONCILE,
        "reconcile one application-owned run from authoritative evidence",
    )
    _add_lifecycle_command(subparsers, ResearchAction.EVIDENCE, "read exact run evidence")
    subparsers.add_parser("diagnose", help="forensic/read-side operator tools")
    subparsers.add_parser("manage", help="platform management and deployment tools")
    _add_project_commands(subparsers)
    return parser


def _load_payload(args: argparse.Namespace):
    if args.payload_file is not None:
        return json.loads(args.payload_file.read_text(encoding="utf-8"))
    if args.payload is not None:
        return json.loads(args.payload)
    return None


def _run_project_lifecycle(args: argparse.Namespace, project_application_loader: ProjectApplicationLoader) -> int:
    loaded = project_application_loader(args.project_root, config_path=args.config)
    application = loaded.application
    target = args.target or loaded.default_target
    facade = ResearchFacade(application)
    operation = getattr(facade, args.action.value)
    result = operation(target, _load_payload(args))
    _emit({"ok": True, "command": args.command, "result": result})
    return 0


def _run_project(args: argparse.Namespace, project_experience: ProjectFacade) -> int:
    if args.project_command == "create":
        destination = args.destination or Path(args.project_id)
        blueprint = (
            None
            if args.blueprint is None
            else decode_research_project_blueprint(args.blueprint.read_bytes())
        )
        receipt = project_experience.create(
            args.project_id,
            args.version,
            destination,
            blueprint,
        )
        _emit({"ok": True, "command": "project create", "result": receipt})
        return 0
    if args.project_command == "doctor":
        report = project_experience.doctor(args.project_root)
        _emit({"ok": report.ready, "command": "project doctor", "result": report}, stream=None if report.ready else sys.stderr)
        return 0 if report.ready else 4
    if args.project_command == "test":
        receipt = project_experience.test(args.project_root)
        _emit({"ok": receipt.passed, "command": "project test", "result": receipt}, stream=None if receipt.passed else sys.stderr)
        return 0 if receipt.passed else 4
    raise ValueError(f"unsupported project command: {args.project_command}")

def run_research_cli(
    argv: list[str] | None,
    *,
    diagnose_main: ResearchCliDelegate,
    manage_main: ResearchCliDelegate,
    project_experience: ProjectFacade,
    project_application_loader: ProjectApplicationLoader,
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
        return _run_project_lifecycle(args, project_application_loader)
    except ResearchOperationFailure as exc:
        _emit({"ok": False, "command": args.command, "result": exc.result}, stream=sys.stderr)
        return 3
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


__all__ = ["ProjectApplicationLoader", "ResearchCliDelegate", "build_research_parser", "run_research_cli"]
