#!/usr/bin/env python3
"""Run one argv command inside an exact profile-bound server checkout."""

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

from noetrium_platform.foundation.kernel.kernel.errors import redact_text
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from scripts.server_common import compose_script_server, server_cli_concurrency_scope
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerRepositoryCommandRequest
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.composition import compose_ssh_server_repository_command


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        separator = raw_argv.index("--")
    except ValueError:
        separator = len(raw_argv)
    command_argv = tuple(raw_argv[separator + 1 :])
    control_argv = raw_argv[:separator]
    parser = argparse.ArgumentParser(
        description="Run one argv command inside an exact profile-bound repository checkout"
    )
    parser.add_argument("server_id")
    parser.add_argument("repository_name")
    parser.add_argument("revision", help="40-character commit SHA")
    parser.add_argument("--cwd", default="", help="repository-relative POSIX working directory")
    parser.add_argument("--profile-file")
    args = parser.parse_args(control_argv)
    if not command_argv:
        parser.error("a command argv is required after --")
    try:
        with server_cli_concurrency_scope("server-repository-command") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            runner = compose_ssh_server_repository_command(
                connection=server.connection,
                repository_root=server.remote_profile.repository_root,
                profile_digest=server.profile_digest,
            )
            receipt = runner.run(
                ServerRepositoryCommandRequest(
                    args.repository_name,
                    args.revision,
                    command_argv,
                    args.cwd,
                ),
                # Repository commands are unattended validation/mutation work;
                # operator TTY access belongs to server_session attach.
                interactive=False,
            )
            result = receipt.command_result
            print(json.dumps({
                "server_id": receipt.server_id,
                "repository_name": receipt.repository_name,
                "revision": receipt.revision,
                "target_path": receipt.target_path,
                "working_directory": receipt.working_directory,
                "command_argv": list(receipt.command_argv),
                "return_code": result.return_code,
                "failure_kind": result.failure_kind.value,
                "succeeded": receipt.succeeded,
                "stdout": redact_text(result.stdout),
                "stderr": redact_text(result.stderr),
                "duration_seconds": result.duration_seconds,
                "profile_digest": server.profile_digest,
                "operation_log": str(server.operation_journal.path),
            }, ensure_ascii=False, sort_keys=True))
            return 0 if receipt.succeeded else 1
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(json.dumps({
            "server_id": args.server_id,
            "repository_name": args.repository_name,
            "revision": args.revision,
            "error_type": type(exc).__name__,
            "error": descriptor.safe_message,
            "error_digest": descriptor.error_digest,
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
