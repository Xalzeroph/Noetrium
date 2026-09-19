#!/usr/bin/env python3
"""Read and reconcile the controller-local server operation ledger.

This command never retries, mutates the remote host, or guesses an outcome.
An operation with a durable ``started`` record and no ``finished`` record is
reported as effect-uncertain and must be reconciled by its owning lifecycle
before the same mutation is submitted again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

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

from scripts.server_common import compose_script_server, load_script_environment, server_cli_concurrency_scope
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationResolved,
    ServerOperationResolution,
)
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerIdentityConfigurationError,
    server_environment_prefix,
)
from noetrium_platform.infrastructure.lifecycle.server.runtime import JsonlServerOperationJournal


def _record_payload(record) -> dict[str, object]:
    finished = record.finished
    return {
        "operation_id": record.operation_id,
        "server_id": record.server_id,
        "kind": record.kind.value,
        "request_digest": record.started.request_digest,
        "profile_digest": record.started.profile_digest,
        "started_at": record.started.started_at,
        "interactive": record.started.interactive,
        "effect": record.started.effect.value,
        "state": record.state.value,
        "effect_uncertain": record.effect_uncertain,
        "finished_at": finished.finished_at if finished is not None else None,
        "return_code": finished.return_code if finished is not None else None,
        "failure_kind": finished.failure_kind if finished is not None else None,
        "error_type": finished.error_type if finished is not None else None,
        "error_digest": finished.error_digest if finished is not None else None,
        "stdout_preview": finished.stdout_preview if finished is not None else None,
        "stderr_preview": finished.stderr_preview if finished is not None else None,
        "resolution": (
            {
                "disposition": record.resolution.disposition.value,
                "resolved_at": record.resolution.resolved_at,
                "evidence_ref": record.resolution.evidence_ref,
                "evidence_digest": record.resolution.evidence_digest,
            }
            if record.resolution is not None
            else None
        ),
    }


def _offline_operation_journal(server_id: str, profile_file: str | None, *, task_group):
    """Open the local ledger without requiring a usable remote identity.

    Reconciliation is a controller-local durability operation. Requiring a
    readable SSH key before resolving a failed remote operation creates a
    deadlock exactly when credentials are the thing being repaired. The
    profile is still loaded and the declared local binding root is used; no
    remote connection or mutation is attempted here.
    """

    environ = load_script_environment(profile_file)
    prefix = server_environment_prefix(server_id)
    raw_root = str(environ.get(f"{prefix}_LOCAL_BINDING_ROOT", "")).strip()
    if not raw_root:
        raise ValueError(f"missing {prefix}_LOCAL_BINDING_ROOT for offline reconciliation")
    binding_root = Path(raw_root).expanduser()
    if not binding_root.is_absolute():
        raise ValueError(f"{prefix}_LOCAL_BINDING_ROOT must be an absolute local path")
    journal_path = binding_root / "server-operations.jsonl"
    identity = hashlib.sha256(str(journal_path.resolve()).encode("utf-8")).hexdigest()[:16]
    actor = task_group.open_serial_actor(
        f"offline-server-operation-journal:{identity}",
        lane_id=f"offline-server-operation-journal-writer:{identity}",
    )
    return JsonlServerOperationJournal(journal_path, writer_actor=actor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect managed server operation evidence")
    parser.add_argument("server_id", help="logical server id; values come from RP_SERVER_<ID>_*")
    parser.add_argument(
        "--profile-file",
        help="literal KEY=value profile; also configurable via RP_SERVER_PROFILE_FILE",
    )
    parser.add_argument("--limit", type=int, default=20, help="number of recent operation records")
    parser.add_argument(
        "--reconcile-operation",
        help="resolve one effect-uncertain operation after independent inspection",
    )
    parser.add_argument(
        "--disposition",
        choices=tuple(item.value for item in ServerOperationResolution),
        help="operator decision for --reconcile-operation",
    )
    parser.add_argument(
        "--evidence-ref",
        help="stable non-secret evidence reference for --reconcile-operation",
    )
    parser.add_argument(
        "--evidence-digest",
        help="SHA-256 digest of the external evidence for --reconcile-operation",
    )
    parser.add_argument(
        "--recorded-profile-digest",
        help="required when reconciling an operation created under an older profile",
    )
    args = parser.parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-operations") as task_group:
            if args.reconcile_operation:
                if not all((args.disposition, args.evidence_ref, args.evidence_digest)):
                    raise ValueError(
                        "--reconcile-operation requires --disposition, --evidence-ref and --evidence-digest"
                    )
                if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,256}", args.evidence_ref) is None:
                    raise ValueError("--evidence-ref contains unsafe or unsupported characters")
                if re.fullmatch(r"[0-9a-fA-F]{64}", args.evidence_digest) is None:
                    raise ValueError("--evidence-digest must be a SHA-256 hex digest")
                try:
                    _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
                    journal = server.operation_journal
                    current_profile_digest = server.profile_digest
                except ServerIdentityConfigurationError:
                    journal = _offline_operation_journal(args.server_id, args.profile_file, task_group=task_group)
                    server = None
                    current_profile_digest = None
                record = journal.read_operation(args.reconcile_operation)
                if record is None:
                    raise ValueError("cannot reconcile an unknown server operation")
                if record.server_id != args.server_id:
                    raise ValueError("operation server id differs from the selected server")
                if current_profile_digest is not None and record.started.profile_digest != current_profile_digest:
                    if re.fullmatch(r"[0-9a-fA-F]{64}", args.recorded_profile_digest or "") is None:
                        raise ValueError(
                            "operation profile digest differs from the current profile; "
                            "provide the recorded profile digest after independent inspection"
                        )
                    if args.recorded_profile_digest.lower() != record.started.profile_digest:
                        raise ValueError("--recorded-profile-digest does not match the operation record")
                elif current_profile_digest is None:
                    if re.fullmatch(r"[0-9a-fA-F]{64}", args.recorded_profile_digest or "") is None:
                        raise ValueError(
                            "remote identity is unavailable; provide the recorded profile digest "
                            "after independent inspection"
                        )
                    if args.recorded_profile_digest.lower() != record.started.profile_digest:
                        raise ValueError("--recorded-profile-digest does not match the operation record")
                resolution_profile_digest = record.started.profile_digest
                journal.record_resolved(
                    ServerOperationResolved(
                        record.operation_id,
                        record.server_id,
                        record.kind,
                        record.started.request_digest,
                        ServerOperationResolution(args.disposition),
                        time.time(),
                        args.evidence_ref,
                        args.evidence_digest.lower(),
                        resolution_profile_digest,
                    )
                )
                print(
                    json.dumps(
                        {
                            "server_id": args.server_id,
                            "operation_id": record.operation_id,
                            "reconciled": True,
                            "disposition": args.disposition,
                            "profile_digest": current_profile_digest,
                            "recorded_profile_digest": resolution_profile_digest,
                            "evidence_ref": args.evidence_ref,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                )
                return 0
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            pending = server.operation_journal.pending_operations(server_id=server.server_id)
            recent = server.operation_journal.recent_operations(
                args.limit,
                server_id=server.server_id,
            )
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(
            json.dumps(
                {
                    "server_id": args.server_id,
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
    payload = {
        "server_id": server.server_id,
        "profile_digest": server.profile_digest,
        "operation_log": str(server.operation_journal.path),
        "reconciliation_required": bool(pending),
        "pending_operations": [_record_payload(record) for record in pending],
        "recent_operations": [_record_payload(record) for record in recent],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
