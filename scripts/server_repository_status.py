#!/usr/bin/env python3
"""Inspect one profile-bound GitHub checkout through the managed server port."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 11):
    raise SystemExit("server management requires controller Python >=3.11")

from scripts.server_common import compose_script_server, server_cli_concurrency_scope
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.composition import compose_ssh_server_repository_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect one managed server repository checkout")
    parser.add_argument("server_id")
    parser.add_argument("repository_name")
    parser.add_argument("--staging-revision")
    parser.add_argument("--profile-file")
    args = parser.parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-repository-status") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            status = compose_ssh_server_repository_sync(
                connection=server.connection,
                repository_root=server.remote_profile.repository_root,
                profile_digest=server.profile_digest,
            ).inspect(
                args.repository_name,
                staging_revision=args.staging_revision,
                interactive=False,
            )
            print(json.dumps({
                "server_id": status.server_id,
                "repository_name": status.repository_name,
                "target_path": status.target_path,
                "exists": status.exists,
                "head": status.head,
                "origin": status.origin,
                "dirty": status.dirty,
                "staging_exists": status.staging_exists,
                "target_kind": status.target_kind,
                "staging_kind": status.staging_kind,
                "target_children": list(status.target_children),
                "profile_digest": server.profile_digest,
                "operation_log": str(server.operation_journal.path),
            }, ensure_ascii=False, sort_keys=True))
            return 0
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(json.dumps({
            "server_id": args.server_id,
            "error_type": type(exc).__name__,
            "error": descriptor.safe_message,
            "error_digest": descriptor.error_digest,
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
