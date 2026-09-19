"""Server lifecycle composition."""

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_local_command_runner
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerConnectionPort,
    ServerFileTransferPort,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import (
    ServerReleaseDeploymentPort,
    ServerReleaseDirectoryPort,
    ServerReleaseLayout,
    ServerRemoteProfile,
    ServerRepositoryCommandPort,
    ServerRepositorySyncPort,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.providers import (
    SSHServerReleaseDirectory,
    SSHServerReleasePublisher,
    SSHGitRepositorySynchronizer,
    SSHGitRepositoryCommandRunner,
    SSHGitBundleRepositorySynchronizer,
)
from noetrium_platform.infrastructure.lifecycle.session.providers import SSHRemoteTmuxSessionControl


def compose_ssh_server_release_publisher(
    *,
    connection: ServerConnectionPort,
    transfer: ServerFileTransferPort,
    python_executable: str,
) -> ServerReleaseDeploymentPort:
    return SSHServerReleasePublisher(connection, transfer, python_executable=python_executable)


def compose_ssh_server_release_directory(
    *,
    connection: ServerConnectionPort,
    layout: ServerReleaseLayout,
) -> ServerReleaseDirectoryPort:
    return SSHServerReleaseDirectory(connection, layout)


def compose_ssh_server_repository_sync(
    *,
    connection: ServerConnectionPort,
    repository_root: str,
    profile_digest: str = "",
) -> ServerRepositorySyncPort:
    return SSHGitRepositorySynchronizer(
        connection,
        repository_root=repository_root,
        profile_digest=profile_digest,
    )


def compose_ssh_server_repository_command(
    *,
    connection: ServerConnectionPort,
    repository_root: str,
    profile_digest: str = "",
) -> ServerRepositoryCommandPort:
    return SSHGitRepositoryCommandRunner(
        connection,
        repository_root=repository_root,
        profile_digest=profile_digest,
    )


def compose_ssh_server_repository_bundle_sync(
    *,
    connection: ServerConnectionPort,
    transfer: ServerFileTransferPort,
    repository_root: str,
    task_group: TaskGroupPort,
    profile_digest: str = "",
) -> SSHGitBundleRepositorySynchronizer:
    return SSHGitBundleRepositorySynchronizer(
        connection,
        transfer,
        local_commands=build_local_command_runner(task_group),
        repository_root=repository_root,
        profile_digest=profile_digest,
    )


def compose_ssh_server_session_control(
    *,
    connection: ServerConnectionPort,
    profile: ServerRemoteProfile,
    interactive: bool,
) -> SSHRemoteTmuxSessionControl:
    """Compose the server-bound session backend at the lifecycle boundary."""

    return SSHRemoteTmuxSessionControl(
        connection,
        tmux_executable=profile.tmux_executable,
        binary_identity_digest=profile.tmux_binary_sha256,
        server_label=profile.tmux_server_label,
        config_file=profile.tmux_config_file,
        socket_directory=profile.tmux_socket_directory,
        remote_env_executable=profile.remote_env_executable,
        sha256sum_executable=profile.sha256sum_executable,
        session_environment=profile.session_environment,
        interactive=interactive,
    )


__all__ = [
    "compose_ssh_server_release_directory",
    "compose_ssh_server_release_publisher",
    "compose_ssh_server_repository_sync",
    "compose_ssh_server_repository_command",
    "compose_ssh_server_repository_bundle_sync",
    "compose_ssh_server_session_control",
]
