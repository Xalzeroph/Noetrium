#!/usr/bin/env python3
"""Produce one read-only, profile-bound diagnostic for a managed server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

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

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from scripts.server_common import (
    compose_script_server_catalog,
    compose_server_from_environment,
    compose_server_operator_session,
    compose_server_session_observation,
    server_health_spec,
    server_cli_concurrency_scope,
)
from noetrium_platform.infrastructure.lifecycle.server.health.composition import (
    compose_server_diagnostic_projector,
    compose_ssh_server_health,
)
from noetrium_platform.infrastructure.lifecycle.server.health.api import ServerSessionDiagnostic


def _operation_payload(record) -> dict[str, object]:
    finished = record.finished
    return {
        "operation_id": record.operation_id,
        "kind": record.kind.value,
        "state": record.state.value,
        "effect": record.started.effect.value,
        "effect_uncertain": record.effect_uncertain,
        "request_digest": record.started.request_digest,
        "profile_digest": record.started.profile_digest,
        "started_at": record.started.started_at,
        "finished_at": finished.finished_at if finished is not None else None,
        "duration_seconds": finished.duration_seconds if finished is not None else None,
        "return_code": finished.return_code if finished is not None else None,
        "failure_kind": finished.failure_kind if finished is not None else None,
        "error_type": finished.error_type if finished is not None else None,
        "error_digest": finished.error_digest if finished is not None else None,
        "stdout_bytes": finished.stdout_bytes if finished is not None else None,
        "stderr_bytes": finished.stderr_bytes if finished is not None else None,
    }


def _session_payload(observation) -> ServerSessionDiagnostic:
    return ServerSessionDiagnostic(
        session_name=observation.session_name,
        state=observation.state.value,
        summary=observation.summary,
        controller_pid=observation.controller_pid,
        reason_code=observation.reason_code,
        evidence_refs=tuple(observation.evidence_refs),
    )


def _report_payload(report) -> dict[str, object]:
    health = report.health
    return {
        "server_id": report.server_id,
        "profile_digest": report.profile_digest,
        "operation_log": report.operation_log,
        "status": report.status.value,
        "ready_for_mutation": report.ready_for_mutation,
        "health": {
            "reachable": health.reachable,
            "host_name": health.host_name,
            "python_version": health.python_version,
            "git_version": health.git_version,
            "tmux_version": health.tmux_version,
            "platform_ready": health.platform_ready,
            "checks": dict(health.checks),
            "issues": list(health.issues),
            "return_code": health.raw.return_code,
            "failure_kind": health.raw.failure_kind.value,
            "duration_seconds": health.raw.duration_seconds,
            "stderr": health.raw.stderr,
        },
        "session": None
        if report.session is None
        else {
            "session_name": report.session.session_name,
            "state": report.session.state,
            "summary": report.session.summary,
            "controller_pid": report.session.controller_pid,
            "reason_code": report.session.reason_code,
            "evidence_refs": list(report.session.evidence_refs),
        },
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "summary": issue.summary,
                "evidence_refs": list(issue.evidence_refs),
                "recommended_action": issue.recommended_action,
            }
            for issue in report.issues
        ],
        "pending_operations": [_operation_payload(record) for record in report.pending_operations],
        "recent_operations": [_operation_payload(record) for record in report.recent_operations],
    }


def _list(args) -> int:
    _environ, catalog = compose_script_server_catalog(args.profile_file)
    payload = {
        "source": catalog.source,
        "server_ids": list(catalog.server_ids),
        "entries": [
            {
                "server_id": entry.server_id,
                "prefix": entry.prefix,
                "configured_fields": list(entry.configured_fields),
                "missing_identity_fields": list(entry.missing_identity_fields),
                "missing_runtime_fields": list(entry.missing_runtime_fields),
                "missing_profile_fields": list(entry.missing_profile_fields),
                "composition_ready": entry.composition_ready,
            }
            for entry in catalog.entries
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(entry.composition_ready for entry in catalog.entries) else 1


def _inspect(args) -> int:
    _environ, catalog = compose_script_server_catalog(args.profile_file)
    entry = catalog.entry(args.server_id)
    if not entry.composition_ready:
        missing = ", ".join(entry.missing_profile_fields)
        raise ValueError(f"server profile is incomplete for {args.server_id}: missing {missing}")
    with server_cli_concurrency_scope("server-doctor") as task_group:
        server = compose_server_from_environment(
            args.server_id,
            environ=catalog.environment_for(args.server_id),
            task_group=task_group,
        )
        health = compose_ssh_server_health().probe(
            server.connection,
            interactive=False,
            specification=server_health_spec(server),
        )
        session = None
        if health.reachable and health.platform_ready:
            try:
                composed = compose_server_operator_session(
                    server,
                    interactive=False,
                    session_name=args.session,
                )
                session = _session_payload(compose_server_session_observation(composed))
            except Exception as exc:
                descriptor = describe_exception(exc)
                session = ServerSessionDiagnostic(
                    session_name=args.session or server.remote_profile.session_name,
                    state="unavailable",
                    summary=(
                        f"persistent operator session observation unavailable: "
                        f"{descriptor.error_type}: {descriptor.safe_message}"
                    ),
                    reason_code="session_observation_unavailable",
                )
        pending = server.operation_journal.pending_operations(server_id=server.server_id)
        recent = server.operation_journal.recent_operations(
            args.recent_limit,
            server_id=server.server_id,
        )
        report = compose_server_diagnostic_projector().project(
            server_id=server.server_id,
            profile_digest=server.profile_digest,
            operation_log=str(server.operation_journal.path),
            health=health,
            pending_operations=pending,
            recent_operations=recent,
            session=session,
        )
        print(json.dumps(_report_payload(report), ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if report.ready_for_mutation else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only diagnostic for profile-managed servers")
    sub = parser.add_subparsers(dest="action", required=True)

    list_command = sub.add_parser("list", help="list declared servers without network access")
    list_command.add_argument("--profile-file", help="literal KEY=value server profile")
    list_command.set_defaults(func=_list)

    inspect = sub.add_parser("inspect", help="probe one server and join health, operations and session facts")
    inspect.add_argument("server_id", help="logical id declared by RP_SERVER_CATALOG_IDS")
    inspect.add_argument("--session", help="optional operator session override")
    inspect.add_argument("--profile-file", help="literal KEY=value server profile")
    inspect.add_argument("--recent-limit", type=int, default=20)
    inspect.set_defaults(func=_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "recent_limit", 1) <= 0:
        print(json.dumps({"error_type": "ArgumentError", "error": "--recent-limit must be positive"}))
        return 2
    try:
        return args.func(args)
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(
            json.dumps(
                {
                    "server_id": getattr(args, "server_id", None),
                    "error_type": descriptor.error_type,
                    "error": descriptor.safe_message,
                    "error_digest": descriptor.error_digest,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
