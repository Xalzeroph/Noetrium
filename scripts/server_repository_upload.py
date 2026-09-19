#!/usr/bin/env python3
"""Upload explicitly selected controller/repository files to a server checkout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import posixpath
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.version_info < (3, 11):
    raise SystemExit("server management requires controller Python >=3.11")

from scripts.server_common import compose_script_server, server_cli_concurrency_scope
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception


def _destination(value: str) -> str:
    normalized = posixpath.normpath(value)
    if value.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ValueError("remote destination must stay inside the repository checkout")
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload selected files to one managed repository checkout")
    parser.add_argument("server_id")
    parser.add_argument("repository_name")
    parser.add_argument("--file", action="append", nargs=2, metavar=("LOCAL", "REPOSITORY_RELATIVE"), required=True)
    parser.add_argument("--profile-file")
    args = parser.parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-repository-upload") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            target_root = posixpath.join(server.remote_profile.repository_root, args.repository_name)
            uploaded: list[str] = []
            for local_text, relative_text in args.file:
                local = Path(local_text).expanduser().resolve()
                if not local.is_file():
                    raise FileNotFoundError(str(local))
                relative = _destination(relative_text)
                remote = posixpath.join(target_root, relative)
                result = server.file_transfer.upload(str(local), remote, interactive=False)
                if not result.succeeded:
                    raise RuntimeError(f"upload failed for {relative} rc={result.return_code}")
                uploaded.append(relative)
            print(json.dumps({
                "server_id": server.server_id,
                "repository_name": args.repository_name,
                "uploaded": uploaded,
                "profile_digest": server.profile_digest,
                "operation_log": str(server.operation_journal.path),
            }, ensure_ascii=False, sort_keys=True))
            return 0
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(json.dumps({
            "server_id": args.server_id,
            "repository_name": args.repository_name,
            "error_type": type(exc).__name__,
            "error": descriptor.safe_message,
            "error_digest": descriptor.error_digest,
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
