#!/usr/bin/env python3
"""Export one exact, clean server checkout as a local Git bundle.

The server remains the source of the verified revision.  This controller only
transports the already-created Git object graph back to the local checkout;
it never runs the scientific test suite locally.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import posixpath
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 11):
    raise SystemExit("server management requires controller Python >=3.11")

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from scripts.server_common import compose_script_server, server_cli_concurrency_scope


_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export one exact server Git revision to a local bundle")
    parser.add_argument("server_id")
    parser.add_argument("repository_name")
    parser.add_argument("revision", help="40-character clean server commit SHA")
    parser.add_argument("--output", type=Path, required=True, help="local .bundle output path")
    parser.add_argument("--profile-file")
    args = parser.parse_args(argv)
    if not _REVISION_RE.fullmatch(args.revision):
        parser.error("revision must be a 40-character commit SHA")
    try:
        with server_cli_concurrency_scope("server-repository-export") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            local_output = args.output.expanduser().resolve()
            target = posixpath.join(server.remote_profile.repository_root, args.repository_name)
            bundle = target + ".export-" + args.revision[:12] + ".bundle"
            export_ref = "refs/temporary/noetrium-export-" + args.revision
            target_q = shlex.quote(target)
            bundle_q = shlex.quote(bundle)
            export_ref_q = shlex.quote(export_ref)
            revision_q = shlex.quote(args.revision)
            command = (
                "set -eu; "
                f"target={target_q}; bundle={bundle_q}; export_ref={export_ref_q}; revision={revision_q}; "
                "test -d \"$target/.git\"; "
                "test \"$(git -C \"$target\" rev-parse HEAD)\" = \"$revision\"; "
                "test -z \"$(git -C \"$target\" status --porcelain)\"; "
                "test ! -e \"$bundle\"; "
                "git -C \"$target\" update-ref \"$export_ref\" \"$revision\"; "
                "git -C \"$target\" bundle create \"$bundle\" \"$export_ref\"; "
                "git -C \"$target\" bundle verify \"$bundle\"; "
                "printf '%s\\n' \"$bundle\""
            )
            cleanup_command = (
                "set -eu; "
                f"target={target_q}; bundle={bundle_q}; export_ref={export_ref_q}; "
                "git -C \"$target\" update-ref -d \"$export_ref\"; "
                "rm -f -- \"$bundle\""
            )
            try:
                created = server.connection.execute(
                    command,
                    interactive=False,
                    effect=ServerOperationEffect.MUTATION,
                    timeout_seconds=server.connection.profile.repository_timeout_seconds,
                )
                if not created.succeeded:
                    raise RuntimeError(f"server bundle creation failed rc={created.return_code}")
                local_output.parent.mkdir(parents=True, exist_ok=True)
                transfer = server.file_transfer.download(bundle, str(local_output), interactive=False)
                if not transfer.succeeded:
                    raise RuntimeError("server Git bundle download failed")
            finally:
                cleanup = server.connection.execute(
                    cleanup_command,
                    interactive=False,
                    effect=ServerOperationEffect.MUTATION,
                )
                if not cleanup.succeeded:
                    raise RuntimeError("server Git bundle cleanup failed")
            print(json.dumps({
                "server_id": server.server_id,
                "repository_name": args.repository_name,
                "revision": args.revision,
                "output": str(local_output),
                "profile_digest": server.profile_digest,
                "operation_log": str(server.operation_journal.path),
            }, ensure_ascii=False, sort_keys=True))
            return 0
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
