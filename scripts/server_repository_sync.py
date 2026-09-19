#!/usr/bin/env python3
"""Synchronize one exact GitHub revision into the profile-owned server root."""

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
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerRepositorySyncRequest
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.composition import (
    compose_ssh_server_repository_bundle_sync,
    compose_ssh_server_repository_sync,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull one exact GitHub revision on a managed server")
    parser.add_argument("server_id")
    parser.add_argument("repository_url")
    parser.add_argument("repository_name")
    parser.add_argument("revision", help="40-character commit SHA")
    parser.add_argument("--profile-file")
    parser.add_argument(
        "--transport",
        choices=("bundle", "remote-git"),
        default="bundle",
        help="bundle uses the local exact Git object graph; remote-git is the explicit legacy route",
    )
    parser.add_argument(
        "--source-repository",
        default=str(ROOT),
        help="local clean Git checkout used by the bundle transport",
    )
    args = parser.parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-repository-sync") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            request = ServerRepositorySyncRequest(
                args.repository_url,
                args.repository_name,
                args.revision,
            )
            # Repository synchronization is an unattended mutation.  It must
            # never turn a missing SSH key into a hidden password prompt.
            if args.transport == "bundle":
                synchronizer = compose_ssh_server_repository_bundle_sync(
                    connection=server.connection,
                    transfer=server.file_transfer,
                    repository_root=server.remote_profile.repository_root,
                    task_group=task_group,
                    profile_digest=server.profile_digest,
                )
                receipt = synchronizer.sync(
                    request,
                    source_repository=args.source_repository,
                    interactive=False,
                )
            else:
                synchronizer = compose_ssh_server_repository_sync(
                    connection=server.connection,
                    repository_root=server.remote_profile.repository_root,
                    task_group=task_group,
                    profile_digest=server.profile_digest,
                )
                receipt = synchronizer.sync(request, interactive=False)
            print(json.dumps({
                "server_id": receipt.server_id,
                "repository_url": receipt.repository_url,
                "repository_name": receipt.repository_name,
                "revision": receipt.revision,
                "target_path": receipt.target_path,
                "transport": args.transport,
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
