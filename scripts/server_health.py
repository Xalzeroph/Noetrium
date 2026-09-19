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

from scripts.server_common import compose_script_server, server_cli_concurrency_scope, server_health_spec
from noetrium_platform.infrastructure.lifecycle.server.health.composition import compose_ssh_server_health
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception


def ready_for_mutation(*, platform_ready: bool, pending_operations: tuple[object, ...]) -> bool:
    """A healthy remote host is not writable while effect recovery is pending."""

    return platform_ready and not pending_operations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a managed server from environment configuration")
    parser.add_argument("server_id", help="logical server id; values come from RP_SERVER_<ID>_*")
    parser.add_argument(
        "--profile-file",
        help="literal KEY=value profile; also configurable via RP_SERVER_PROFILE_FILE",
    )
    args = parser.parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-health") as task_group:
            _environ, server = compose_script_server(
                args.server_id, profile_file=args.profile_file, task_group=task_group
            )
            connection = server.connection
            report = compose_ssh_server_health().probe(
                connection,
                interactive=False,
                specification=server_health_spec(server),
            )
            pending_operations = server.operation_journal.pending_operations(server_id=server.server_id)
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(json.dumps({
            "server_id": args.server_id,
            "error_type": type(exc).__name__,
            "error": descriptor.safe_message,
            "error_digest": descriptor.error_digest,
        }))
        return 2
    payload = {
        "server_id": report.server_id,
        "reachable": report.reachable,
        "host_name": report.host_name,
        "python_version": report.python_version,
        "git_version": report.git_version,
        "tmux_version": report.tmux_version,
        "platform_ready": report.platform_ready,
        "checks": dict(report.checks),
        "issues": list(report.issues),
        "profile_digest": server.profile_digest,
        "operation_log": str(server.operation_journal.path),
        "return_code": report.raw.return_code,
        "failure_kind": report.raw.failure_kind.value,
        "duration_seconds": report.raw.duration_seconds,
        "stderr": report.raw.stderr,
        "pending_operations": [
            {
                "operation_id": record.operation_id,
                "kind": record.kind.value,
                "request_digest": record.started.request_digest,
                "started_at": record.started.started_at,
                "state": record.state.value,
                "effect_uncertain": record.effect_uncertain,
            }
            for record in pending_operations
        ],
        "reconciliation_required": bool(pending_operations),
        "ready_for_mutation": ready_for_mutation(
            platform_ready=report.platform_ready,
            pending_operations=pending_operations,
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["ready_for_mutation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
