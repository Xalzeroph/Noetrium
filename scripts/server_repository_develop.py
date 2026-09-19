#!/usr/bin/env python3
"""Run one explicitly authorized command in a server-first repository workspace.

Unlike ``server_repository_command.py``, this entrypoint can continue a known
dirty development checkout.  The caller must opt into that state explicitly;
the profile-bound server identity, exact base revision, operation ledger and
non-interactive transport remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 11):
    raise SystemExit("server management requires controller Python >=3.11")

from noetrium_platform.foundation.kernel.kernel.errors import redact_text
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from scripts.server_common import compose_script_server, server_cli_concurrency_scope


_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _relative_cwd(value: str) -> str:
    if not value:
        return "."
    if value.startswith("/") or posixpath.normpath(value) == ".." or posixpath.normpath(value).startswith("../"):
        raise ValueError("repository working directory must stay inside the checkout")
    return posixpath.normpath(value)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        separator = raw_argv.index("--")
    except ValueError:
        separator = len(raw_argv)
    command_argv = tuple(raw_argv[separator + 1 :])
    control_argv = raw_argv[:separator]
    parser = argparse.ArgumentParser(
        description="Run one explicit development command in a managed server checkout"
    )
    parser.add_argument("server_id")
    parser.add_argument("repository_name")
    parser.add_argument("revision", help="40-character base commit SHA")
    parser.add_argument("--cwd", default="", help="repository-relative working directory")
    parser.add_argument("--allow-dirty", action="store_true", help="continue a pre-existing dirty workspace")
    parser.add_argument("--profile-file")
    args = parser.parse_args(control_argv)
    if not _REVISION_RE.fullmatch(args.revision):
        parser.error("revision must be a 40-character commit SHA")
    if not command_argv:
        parser.error("a command argv is required after --")
    try:
        with server_cli_concurrency_scope("server-repository-develop") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            target = posixpath.join(server.remote_profile.repository_root, args.repository_name)
            cwd = posixpath.join(target, _relative_cwd(args.cwd))
            target_q = shlex.quote(target)
            cwd_q = shlex.quote(cwd)
            expected_q = shlex.quote(args.revision)
            workspace_gate = (
                'test -d "$cwd"; '
                if args.allow_dirty
                else 'test -z "$(git -C "$target" status --porcelain)"; test -d "$cwd"; '
            )
            command = (
                "set -eu; "
                f"target={target_q}; cwd={cwd_q}; expected={expected_q}; "
                "test -d \"$target/.git\"; "
                "test \"$(git -C \"$target\" rev-parse HEAD)\" = \"$expected\"; "
                + workspace_gate
                + f"cd \"$cwd\"; exec {shlex.join(command_argv)}"
            )
            result = server.connection.execute(
                "".join(command),
                interactive=False,
                effect=ServerOperationEffect.MUTATION,
                timeout_seconds=server.connection.profile.repository_timeout_seconds,
            )
            print(json.dumps({
                "server_id": server.server_id,
                "repository_name": args.repository_name,
                "revision": args.revision,
                "target_path": target,
                "working_directory": cwd,
                "allow_dirty": args.allow_dirty,
                "command_argv": list(command_argv),
                "return_code": result.return_code,
                "failure_kind": result.failure_kind.value,
                "succeeded": result.succeeded,
                "stdout": redact_text(result.stdout),
                "stderr": redact_text(result.stderr),
                "duration_seconds": result.duration_seconds,
                "profile_digest": server.profile_digest,
                "operation_log": str(server.operation_journal.path),
            }, ensure_ascii=False, sort_keys=True))
            return 0 if result.succeeded else 1
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
