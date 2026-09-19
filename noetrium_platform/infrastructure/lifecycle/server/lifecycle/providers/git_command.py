from __future__ import annotations

import posixpath
import shlex

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionPort

from ..api import (
    ServerRepositoryCommandPort,
    ServerRepositoryCommandReceipt,
    ServerRepositoryCommandRequest,
)


def _shell(value: str) -> str:
    return shlex.quote(value)


class SSHGitRepositoryCommandRunner(ServerRepositoryCommandPort):
    """Run one argv command inside a profile-owned exact Git checkout."""

    def __init__(
        self,
        connection: ServerConnectionPort,
        *,
        repository_root: str,
        profile_digest: str = "",
    ) -> None:
        if not repository_root.startswith("/") or repository_root == "/":
            raise ValueError("repository_root must be a non-root absolute POSIX path")
        self._connection = connection
        self._repository_root = posixpath.normpath(repository_root)
        self._profile_digest = profile_digest

    def run(
        self,
        request: ServerRepositoryCommandRequest,
        *,
        interactive: bool = False,
    ) -> ServerRepositoryCommandReceipt:
        target = posixpath.join(self._repository_root, request.repository_name)
        working_directory = (
            target
            if not request.relative_cwd
            else posixpath.join(target, request.relative_cwd)
        )
        target_q = _shell(target)
        cwd_q = _shell(working_directory)
        revision_q = _shell(request.revision)
        argv = shlex.join(request.command_argv)
        command = (
            "set -eu; "
            f"target={target_q}; cwd={cwd_q}; expected={revision_q}; "
            "test -d \"$target/.git\"; "
            "test \"$(git -C \"$target\" rev-parse HEAD)\" = \"$expected\"; "
            "test -z \"$(git -C \"$target\" status --porcelain)\"; "
            "test -d \"$cwd\"; "
            "cd \"$cwd\"; "
            f"exec {argv}"
        )
        result = self._connection.execute(
            command,
            interactive=interactive,
            effect=ServerOperationEffect.MUTATION,
            timeout_seconds=self._connection.profile.repository_timeout_seconds,
        )
        return ServerRepositoryCommandReceipt(
            self._connection.profile.server_id,
            request.repository_name,
            request.revision,
            target,
            working_directory,
            request.command_argv,
            result,
            self._profile_digest,
        )


__all__ = ["SSHGitRepositoryCommandRunner"]
