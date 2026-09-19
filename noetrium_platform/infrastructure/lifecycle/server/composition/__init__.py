from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerConnectionProfile,
    ServerConnectionPort,
    ServerFileTransferPort,
)
from noetrium_platform.infrastructure.lifecycle.server.identity.composition import ServerIdentityComposition
from noetrium_platform.infrastructure.lifecycle.server.identity.providers import load_server_profile_environment
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerRemoteProfile
from noetrium_platform.infrastructure.lifecycle.server.providers import (
    ObservedServerConnection,
    ObservedServerFileTransfer,
    ProfileBoundServerConnection,
)
from noetrium_platform.infrastructure.lifecycle.server.runtime import JsonlServerOperationJournal


@dataclass(frozen=True, slots=True)
class ServerManagementComposition:
    """One immutable server binding used by health, session and release roots.

    This is a composition result, not a locator.  It records the exact
    connection and remote-runtime projections materialized from one
    environment mapping and gives all side effects the same local operation
    journal.
    """

    server_id: str
    profile_digest: str
    connection_profile: ServerConnectionProfile
    remote_profile: ServerRemoteProfile
    connection: ServerConnectionPort
    file_transfer: ServerFileTransferPort
    operation_journal: JsonlServerOperationJournal


def compose_environment_server(
    server_id: str,
    *,
    environ: Mapping[str, str],
    identity: ServerIdentityComposition,
    task_group: TaskGroupPort,
) -> ServerManagementComposition:
    """Materialize one server exactly once at the outer composition root."""

    connection = identity.connection_factory.from_environment(server_id, environ=environ)
    file_transfer = identity.file_transfer_factory.from_environment(server_id, environ=environ)
    remote_profile = ServerRemoteProfile.from_environment(server_id, environ=environ)
    if connection.profile != file_transfer.profile:
        raise ValueError("server management connection and transfer identities differ")
    if connection.profile.server_id != remote_profile.server_id:
        raise ValueError("server management identity and remote profile server ids differ")
    profile_digest = canonical_digest(
        {
            "server_id": server_id,
            "connection": {
                "host": connection.profile.host,
                "port": connection.profile.port,
                "username": connection.profile.username,
                "key_path": str(connection.profile.key_path) if connection.profile.key_path else None,
                "known_hosts_path": str(connection.profile.known_hosts_path) if connection.profile.known_hosts_path else None,
                "ssh_config_path": str(connection.profile.ssh_config_path) if connection.profile.ssh_config_path else None,
                "ssh_executable": connection.profile.ssh_executable,
                "control_path": str(connection.profile.control_path) if connection.profile.control_path else None,
                "control_persist_seconds": connection.profile.control_persist_seconds,
                "command_timeout_seconds": connection.profile.command_timeout_seconds,
                "interactive_timeout_seconds": connection.profile.interactive_timeout_seconds,
                "transfer_timeout_seconds": connection.profile.transfer_timeout_seconds,
                "repository_timeout_seconds": connection.profile.repository_timeout_seconds,
                "git_transport_timeout_seconds": connection.profile.git_transport_timeout_seconds,
                "output_limit_bytes": connection.profile.output_limit_bytes,
            },
            "file_transfer": {
                "executable": getattr(file_transfer, "executable", ""),
            },
            "remote": {
                "platform_root": remote_profile.platform_root,
                "release_root": remote_profile.release_root,
                "operator_cwd": remote_profile.operator_cwd,
                "repository_root": remote_profile.repository_root,
                "operator_shell": remote_profile.operator_shell,
                "operator_shell_args": remote_profile.operator_shell_args,
                "remote_env_executable": remote_profile.remote_env_executable,
                "sha256sum_executable": remote_profile.sha256sum_executable,
                "python_executable": remote_profile.python_executable,
                "python_binary_sha256": remote_profile.python_binary_sha256,
                "python_packages_sha256": remote_profile.python_packages_sha256,
                "node_executable": remote_profile.node_executable,
                "node_binary_sha256": remote_profile.node_binary_sha256,
                "java_executable": remote_profile.java_executable,
                "java_binary_sha256": remote_profile.java_binary_sha256,
                "platform_management_executable": remote_profile.platform_management_executable,
                "platform_management_binary_sha256": remote_profile.platform_management_binary_sha256,
                "tmux_executable": remote_profile.tmux_executable,
                "tmux_binary_sha256": remote_profile.tmux_binary_sha256,
                "tmux_server_label": remote_profile.tmux_server_label,
                "tmux_config_file": remote_profile.tmux_config_file,
                "tmux_socket_directory": remote_profile.tmux_socket_directory,
                "session_name": remote_profile.session_name,
                "remote_home": remote_profile.remote_home,
                "remote_path": remote_profile.remote_path,
                "remote_term": remote_profile.remote_term,
            },
        }
    )
    journal_path = remote_profile.local_binding_root / "server-operations.jsonl"
    journal_identity = hashlib.sha256(str(journal_path.resolve()).encode("utf-8")).hexdigest()[:16]
    journal_actor = task_group.open_serial_actor(
        f"server-operation-journal:{journal_identity}",
        lane_id=f"server-operation-journal-writer:{journal_identity}",
    )
    journal = JsonlServerOperationJournal(journal_path, writer_actor=journal_actor)
    profile_bound_connection = ProfileBoundServerConnection(connection, remote_profile)
    return ServerManagementComposition(
        server_id,
        profile_digest,
        connection.profile,
        remote_profile,
        ObservedServerConnection(profile_bound_connection, journal, profile_digest=profile_digest),
        ObservedServerFileTransfer(file_transfer, journal, profile_digest=profile_digest),
        journal,
    )


def load_server_management_environment(
    profile_file: str | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Load the one literal profile source used by every server entry point."""

    import os

    selected = profile_file or (os.environ if environ is None else environ).get(
        "RP_SERVER_PROFILE_FILE", ""
    ).strip()
    return load_server_profile_environment(selected, base=environ) if selected else (
        os.environ if environ is None else environ
    )


__all__ = [
    "ServerManagementComposition",
    "compose_environment_server",
    "load_server_management_environment",
]
