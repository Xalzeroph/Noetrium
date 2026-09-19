from __future__ import annotations

import posixpath
import re
import shlex

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionPort

from ..api import (
    ServerRepositorySyncError,
    ServerRepositorySyncReceipt,
    ServerRepositorySyncRequest,
    ServerRepositorySyncPort,
    ServerRepositoryStatus,
)


_REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_GIT_HTTP_CONNECT_TIMEOUT_SECONDS = 15
_GIT_HTTP_LOW_SPEED_LIMIT_BYTES = 1024
_GIT_HTTP_LOW_SPEED_TIME_SECONDS = 60
_GIT_WATCHDOG_KILL_AFTER_SECONDS = 10


def _shell(value: str) -> str:
    return shlex.quote(value)


class SSHGitRepositorySynchronizer(ServerRepositorySyncPort):
    """Synchronize one exact GitHub revision through the managed SSH port.

    The operator cwd is the only remote repository-root authority. Existing
    checkouts must be clean and must point at the requested origin; the
    synchronizer never resets or overwrites a dirty worktree.
    """

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

    def sync(
        self,
        request: ServerRepositorySyncRequest,
        *,
        interactive: bool = False,
    ) -> ServerRepositorySyncReceipt:
        target = posixpath.join(self._repository_root, request.repository_name)
        staging = target + ".staging-" + request.revision[:12]
        url = _shell(request.repository_url)
        target_q = _shell(target)
        staging_q = _shell(staging)
        revision_q = _shell(request.revision)
        git_deadline = f"{self._connection.profile.git_transport_timeout_seconds:g}s"
        git_watchdog = (
            "timeout --foreground --signal=TERM "
            f"--kill-after={_GIT_WATCHDOG_KILL_AFTER_SECONDS}s {git_deadline} "
        )
        command = (
            "set -eu; export GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false; "
            "command -v timeout >/dev/null; "
            f"root={_shell(self._repository_root)}; target={target_q}; staging={staging_q}; "
            "mkdir -p -- \"$root\"; "
            "if [ -e \"$target\" ] && [ ! -d \"$target/.git\" ]; then "
            "printf 'target-not-git\\n' >&2; exit 21; fi; "
            "if [ -d \"$target/.git\" ]; then "
            "test -z \"$(git -C \"$target\" status --porcelain)\"; "
            f"test \"$(git -C \"$target\" remote get-url origin)\" = {url}; "
            f"{git_watchdog}git -C \"$target\" -c credential.interactive=false "
            f"-c http.connectTimeout={_GIT_HTTP_CONNECT_TIMEOUT_SECONDS} "
            f"-c http.lowSpeedLimit={_GIT_HTTP_LOW_SPEED_LIMIT_BYTES} "
            f"-c http.lowSpeedTime={_GIT_HTTP_LOW_SPEED_TIME_SECONDS} "
            "fetch --prune origin master; "
            f"git -C \"$target\" rev-parse --verify {revision_q}^{{commit}} >/dev/null; "
            f"git -C \"$target\" checkout --detach {revision_q}; "
            "else "
            f"test ! -e \"$staging\"; {git_watchdog}git clone --branch master --single-branch "
            f"--config credential.interactive=false "
            f"--config http.connectTimeout={_GIT_HTTP_CONNECT_TIMEOUT_SECONDS} "
            f"--config http.lowSpeedLimit={_GIT_HTTP_LOW_SPEED_LIMIT_BYTES} "
            f"--config http.lowSpeedTime={_GIT_HTTP_LOW_SPEED_TIME_SECONDS} "
            f"{url} \"$staging\"; "
            f"git -C \"$staging\" rev-parse --verify {revision_q}^{{commit}} >/dev/null; "
            f"git -C \"$staging\" checkout --detach {revision_q}; "
            "mv -- \"$staging\" \"$target\"; fi; "
            f"test \"$(git -C \"$target\" rev-parse HEAD)\" = {revision_q}; "
            "test -z \"$(git -C \"$target\" status --porcelain)\"; "
            "printf 'repository=%s\\nrevision=%s\\ntarget=%s\\n' "
            "\"$(git -C \"$target\" remote get-url origin)\" "
            "\"$(git -C \"$target\" rev-parse HEAD)\" \"$target\""
        )
        result = self._connection.execute(
            command,
            interactive=interactive,
            effect=ServerOperationEffect.MUTATION,
            timeout_seconds=self._connection.profile.repository_timeout_seconds,
        )
        if not result.succeeded:
            raise ServerRepositorySyncError(
                "sync",
                f"remote command failed rc={result.return_code} failure={result.failure_kind}",
            )
        return ServerRepositorySyncReceipt(
            self._connection.profile.server_id,
            request.repository_url,
            request.repository_name,
            request.revision,
            target,
            result.return_code,
            self._profile_digest,
        )

    def inspect(
        self,
        repository_name: str,
        *,
        staging_revision: str | None = None,
        interactive: bool = False,
    ) -> ServerRepositoryStatus:
        if _REPOSITORY_NAME_RE.fullmatch(repository_name) is None:
            raise ValueError("repository_name contains unsafe or unsupported characters")
        target = posixpath.join(self._repository_root, repository_name)
        target_q = _shell(target)
        if staging_revision:
            staging = target + ".staging-" + staging_revision[:12]
            staging_q = _shell(staging)
            staging_probe = (
                f"if [ -L {staging_q} ]; then printf 'staging_kind=symlink\\nstaging=1\\n'; "
                f"elif [ -d {staging_q} ]; then printf 'staging_kind=directory\\nstaging=1\\n'; "
                f"elif [ -f {staging_q} ]; then printf 'staging_kind=file\\nstaging=1\\n'; "
                f"elif [ -e {staging_q} ]; then printf 'staging_kind=other\\nstaging=1\\n'; "
                "else printf 'staging_kind=absent\\nstaging=0\\n'; fi; "
            )
        else:
            staging_probe = "printf 'staging_kind=absent\\nstaging=0\\n'; "
        command = (
            "set -eu; "
            f"target={target_q}; "
            "target_children=; "
            "if [ -d \"$target\" ] && [ ! -d \"$target/.git\" ]; then "
            "target_children=\"$(find \"$target\" -mindepth 1 -maxdepth 1 -printf '%f\\n' "
            "| LC_ALL=C sort | head -128 | paste -sd, -)\"; fi; "
            "if [ -d \"$target/.git\" ]; then "
            "printf 'target_kind=git\\nexists=1\\nhead=%s\\norigin=%s\\ndirty=%s\\n' "
            "\"$(git -C \"$target\" rev-parse HEAD)\" "
            "\"$(git -C \"$target\" remote get-url origin)\" "
            "\"$(if [ -n \"$(git -C \"$target\" status --porcelain)\" ]; then printf 1; else printf 0; fi)\"; "
            "elif [ -L \"$target\" ]; then printf 'target_kind=symlink\\nexists=0\\nhead=\\norigin=\\ndirty=\\n'; "
            "elif [ -d \"$target\" ]; then printf 'target_kind=directory\\nexists=0\\nhead=\\norigin=\\ndirty=\\n'; "
            "elif [ -f \"$target\" ]; then printf 'target_kind=file\\nexists=0\\nhead=\\norigin=\\ndirty=\\n'; "
            "elif [ -e \"$target\" ]; then printf 'target_kind=other\\nexists=0\\nhead=\\norigin=\\ndirty=\\n'; "
            "else printf 'target_kind=absent\\nexists=0\\nhead=\\norigin=\\ndirty=\\n'; fi; "
            + staging_probe
            + "printf 'target_children=%s\\n' \"$target_children\""
        )
        result = self._connection.execute(
            command,
            interactive=interactive,
            effect=ServerOperationEffect.OBSERVATION,
        )
        if not result.succeeded:
            raise ServerRepositorySyncError(
                "inspect",
                f"remote command failed rc={result.return_code} failure={result.failure_kind}",
            )
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        required = {
            "target_kind",
            "exists",
            "head",
            "origin",
            "dirty",
            "staging_kind",
            "staging",
            "target_children",
        }
        if set(values) != required:
            raise ServerRepositorySyncError("inspect", "remote status violated the repository status contract")
        exists = values["exists"] == "1"
        dirty = None if not exists else values["dirty"] == "1"
        return ServerRepositoryStatus(
            self._connection.profile.server_id,
            repository_name,
            target,
            exists,
            values["head"] or None,
            values["origin"] or None,
            dirty,
            values["staging"] == "1",
            values["target_kind"],
            values["staging_kind"],
            tuple(item for item in values["target_children"].split(",") if item),
        )


__all__ = ["SSHGitRepositorySynchronizer"]
