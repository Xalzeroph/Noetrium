#!/usr/bin/env python3
"""Operate one environment-configured persistent server operator session.

The script is deliberately thin: server identity, remote runtime paths,
tmux transport attestation, durable bindings and reconciliation belong to
their respective platform ports. It does not contain a second server registry
or a remote shell command builder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 11):
    print(
        json.dumps(
            {
                "error_type": "ControllerPythonVersionError",
                "error": "server management requires controller Python >=3.11",
                "detected": ".".join(str(part) for part in sys.version_info[:3]),
            },
            sort_keys=True,
        )
    )
    raise SystemExit(2)

from scripts.server_common import (
    compose_script_server,
    compose_server_operator_session,
    compose_server_session_observation,
    server_cli_concurrency_scope,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception


def _observation_payload(observation) -> dict[str, object]:
    return {
        "session": observation.session_name,
        "state": observation.state.value,
        "summary": observation.summary,
        "controller_pid": observation.controller_pid,
        "evidence_refs": list(observation.evidence_refs),
        "attach_argv": list(observation.attach_argv),
        "reason_code": observation.reason_code,
    }


def _emit(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _ensure(args, task_group) -> int:
    _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
    composed = compose_server_operator_session(
        server,
        interactive=False,
        session_name=args.session,
    )
    report = composed.manager.ensure(composed.spec)
    return _emit(
        {
            "server_id": server.server_id,
            "session": composed.spec.session_name,
            "persistent": True,
            "reused": report.reused,
            "spec_digest": report.spec_digest,
            "transport_identity_digest": composed.manager.transport_identity_digest,
            "transport_identity_verified": composed.manager.transport_identity_verified,
            "profile_digest": server.profile_digest,
            "operation_log": str(server.operation_journal.path),
            "controller_pid": report.snapshot.controller_pid,
            "cwd": composed.spec.cwd,
            "attach_argv": list(report.attach_argv),
            "evidence_refs": list(report.evidence_refs),
        }
    )


def _status(args, task_group) -> int:
    _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
    composed = compose_server_operator_session(
        server,
        interactive=False,
        session_name=args.session,
    )
    observation = compose_server_session_observation(composed)
    payload = {
        "server_id": server.server_id,
        "profile_digest": server.profile_digest,
        "operation_log": str(server.operation_journal.path),
    }
    payload.update(_observation_payload(observation))
    return _emit(payload)


def _attach(args, task_group) -> int:
    _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
    composed = compose_server_operator_session(server, interactive=True, session_name=args.session)
    return server.connection.run_interactive(composed.manager.attach(composed.spec))


def _terminate(args, task_group) -> int:
    _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
    composed = compose_server_operator_session(
        server,
        interactive=False,
        session_name=args.session,
    )
    evidence_refs = composed.manager.terminate(composed.spec)
    return _emit(
        {
            "server_id": server.server_id,
            "session": composed.spec.session_name,
            "terminated": True,
            "profile_digest": server.profile_digest,
            "operation_log": str(server.operation_journal.path),
            "evidence_refs": list(evidence_refs),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a persistent remote operator session")
    sub = parser.add_subparsers(dest="action", required=True)

    def common(command):
        command.add_argument("server_id", help="logical id from RP_SERVER_<ID>_*")
        command.add_argument("--session", help="optional override of the profile session name")
        command.add_argument(
            "--profile-file",
            help="literal KEY=value profile; also configurable via RP_SERVER_PROFILE_FILE",
        )

    ensure = sub.add_parser("ensure")
    common(ensure)
    ensure.set_defaults(func=_ensure)

    status = sub.add_parser("status")
    common(status)
    status.set_defaults(func=_status)

    attach = sub.add_parser("attach")
    attach.add_argument("server_id", help="logical id from RP_SERVER_<ID>_*")
    attach.add_argument("--session", help="optional override of the profile session name")
    attach.add_argument(
        "--profile-file",
        help="literal KEY=value profile; also configurable via RP_SERVER_PROFILE_FILE",
    )
    attach.set_defaults(func=_attach)

    terminate = sub.add_parser("terminate")
    common(terminate)
    terminate.set_defaults(func=_terminate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-session") as task_group:
            return args.func(args, task_group)
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(
            json.dumps(
                {
                    "server_id": getattr(args, "server_id", None),
                    "error_type": type(exc).__name__,
                    "error": descriptor.safe_message,
                    "error_digest": descriptor.error_digest,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
