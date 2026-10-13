"""Server lifecycle composition."""

from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
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
    local_commands: LocalCommandRunnerPort,
    profile_digest: str = "",
) -> SSHGitBundleRepositorySynchronizer:
    return SSHGitBundleRepositorySynchronizer(
        connection,
        transfer,
        local_commands=local_commands,
        repository_root=repository_root,
        profile_digest=profile_digest,
    )



__all__ = [
    "compose_ssh_server_release_directory",
    "compose_ssh_server_release_publisher",
    "compose_ssh_server_repository_sync",
    "compose_ssh_server_repository_command",
    "compose_ssh_server_repository_bundle_sync",
]
