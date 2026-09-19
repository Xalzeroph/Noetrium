#!/usr/bin/env python3
"""Launch the frozen runtime controller on a managed server.

This is the only runtime-controller composition entry.  Connection identity,
remote paths, tmux identity, operation observation and durable local state all
come from one server profile.  The run manifest owns the controller argv; this
script accepts no replacement command, release root or tmux executable.
"""

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

from scripts.server_common import compose_script_server, server_cli_concurrency_scope
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.research.experimentation.run.manifest.runtime import load_run_launch_manifest
from noetrium_platform.foundation.governance.release.runtime.active_pin_store import ActiveReleasePinStore
from noetrium_platform.infrastructure.lifecycle.host.bootstrap.runtime import (
    DirectoryServerBootstrapStateStore,
    ServerBootstrapTransaction,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerReleaseLayout
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.composition import (
    compose_ssh_server_release_directory,
    compose_ssh_server_session_control,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.runtime import ServerRuntimeBootstrap
from noetrium_platform.infrastructure.lifecycle.session.api import ServerSessionPolicy
from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    DirectoryPersistentSessionBindingStore,
    PersistentSessionManager,
    RuntimePersistentSessionHost,
    load_controller_environment,
)


def _runtime(args, task_group) -> int:
    _environ, server = compose_script_server(
        args.server_id, profile_file=args.profile_file, task_group=task_group
    )
    manifest = load_run_launch_manifest(args.manifest_file)
    controller_environment = load_controller_environment(args.controller_environment_file)
    profile = server.remote_profile
    effective_control_id = f"{args.control_id}:server-profile:{server.profile_digest}"
    runtime_root = profile.local_binding_root / "runtime-controller"
    bindings = DirectoryPersistentSessionBindingStore(runtime_root / "session-bindings")
    control = compose_ssh_server_session_control(
        connection=server.connection,
        profile=profile,
        interactive=False,
    )
    sessions = PersistentSessionManager(control, bindings)
    host = RuntimePersistentSessionHost(sessions)
    transaction = ServerBootstrapTransaction(
        DirectoryServerBootstrapStateStore(runtime_root / "bootstrap"),
        ActiveReleasePinStore(runtime_root / "release-pins"),
        sessions,
    )
    layout = compose_ssh_server_release_directory(
        connection=server.connection,
        layout=ServerReleaseLayout(profile.release_root),
    )
    report = ServerRuntimeBootstrap(
        layout,
        host,
        transaction,
        ServerSessionPolicy(host.transport_backend_id, host.transport_identity_digest),
    ).ensure_controller(
        manifest,
        control_id=effective_control_id,
        controller_environment=controller_environment,
    )
    print(
        json.dumps(
            {
                "server_id": server.server_id,
                "control_id": args.control_id,
                "effective_control_id": effective_control_id,
                "release_dir": str(report.release_dir),
                "runtime_manifest_digest": report.runtime_manifest_digest,
                "server_session_policy_digest": report.server_session_policy_digest,
                "bootstrap_phase": report.bootstrap_phase,
                "bootstrap_revision": report.bootstrap_revision,
                "session": report.session.snapshot.session_name,
                "session_controller_pid": report.session.snapshot.controller_pid,
                "session_reused": report.session.reused,
                "profile_digest": server.profile_digest,
                "operation_log": str(server.operation_journal.path),
                "evidence_refs": list(report.bootstrap_evidence_refs),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Launch the exact run-manifest controller on a managed server"
    )
    parser.add_argument("server_id", help="logical id from RP_SERVER_<ID>_*")
    parser.add_argument("--control-id", required=True, help="stable runtime controller identity")
    parser.add_argument("--manifest-file", required=True, help="local frozen RunLaunchManifest JSON")
    parser.add_argument(
        "--controller-environment-file",
        help="optional literal local KEY=value controller environment",
    )
    parser.add_argument(
        "--profile-file",
        help="literal server profile; also configurable via RP_SERVER_PROFILE_FILE",
    )
    args = parser.parse_args(argv)
    try:
        with server_cli_concurrency_scope("server-runtime") as task_group:
            return _runtime(args, task_group)
    except Exception as exc:
        descriptor = describe_exception(exc)
        print(
            json.dumps(
                {
                    "server_id": args.server_id,
                    "control_id": args.control_id,
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


if __name__ == "__main__":
    raise SystemExit(main())
