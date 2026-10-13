from __future__ import annotations

import argparse
import hashlib
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

from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import (
    ServerReleaseDeploymentRequest,
    ServerReleaseLayout,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.composition import (
    compose_ssh_server_release_publisher,
)
from scripts.server_common import compose_script_server, server_cli_concurrency_scope
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish one exact release package to a managed server")
    parser.add_argument("server_id", help="logical server id; values come from RP_SERVER_<ID>_*")
    parser.add_argument("package", type=Path, help="local official release ZIP")
    parser.add_argument(
        "--profile-file",
        help="literal KEY=value profile; also configurable via RP_SERVER_PROFILE_FILE",
    )
    args = parser.parse_args(argv)
    package = args.package.expanduser().resolve()
    try:
        with server_cli_concurrency_scope("server-release-publish") as task_group:
            _environ, server = compose_script_server(args.server_id, profile_file=args.profile_file, task_group=task_group)
            connection = server.connection
            transfer = server.file_transfer
            publisher = compose_ssh_server_release_publisher(
                connection=connection,
                transfer=transfer,
                python_executable=server.remote_profile.python_executable,
            )
            receipt = publisher.publish(
                ServerReleaseDeploymentRequest(
                    release_digest=_sha256(package),
                    local_package=package,
                    layout=ServerReleaseLayout(server.remote_profile.release_root),
                ),
                interactive=False,
            )
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(json.dumps({
            "server_id": args.server_id,
            "error_type": type(exc).__name__,
            "error": descriptor.safe_message,
            "error_digest": descriptor.error_digest,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({
        "server_id": receipt.server_id,
        "release_digest": receipt.release_digest,
        "remote_archive": receipt.remote_archive,
        "remote_release_dir": receipt.remote_release_dir,
        "uploaded": receipt.uploaded,
        "preparation_return_code": receipt.preparation.return_code,
        "transfer_return_code": receipt.transfer.return_code if receipt.transfer else None,
        "finalization_return_code": receipt.finalization.return_code if receipt.finalization else None,
        "profile_digest": server.profile_digest,
        "operation_log": str(server.operation_journal.path),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
