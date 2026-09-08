from __future__ import annotations

from pathlib import Path
import posixpath
import re
import shlex
import tempfile

from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandExecutionError,
    LocalCommandResult,
    LocalCommandRunnerPort,
)
from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerConnectionPort,
    ServerFileTransferPort,
)

from ..api import (
    ServerRepositorySyncError,
    ServerRepositorySyncReceipt,
    ServerRepositorySyncRequest,
    ServerRepositoryStatus,
)
from .git_repository import SSHGitRepositorySynchronizer


_GITHUB_IDENTITY_RE = re.compile(
    r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:\.git)?$"
)
_LOCAL_GIT_TIMEOUT_SECONDS = 120.0


def _shell(value: str) -> str:
    return shlex.quote(value)


def _github_identity(value: str) -> str:
    match = _GITHUB_IDENTITY_RE.fullmatch(value.strip())
    if match is None:
        raise ServerRepositorySyncError(
            "bundle-source",
            f"local origin is not a supported GitHub identity: {value!r}",
        )
    return match.group(1).lower()


def _require_local_git(
    local_commands: LocalCommandRunnerPort,
    source_repository: Path,
    request: ServerRepositorySyncRequest,
) -> str:
    def run_git(arguments: tuple[str, ...]) -> LocalCommandResult:
        try:
            return local_commands.run(
                ("git", *arguments),
                cwd=source_repository,
                timeout_seconds=_LOCAL_GIT_TIMEOUT_SECONDS,
            )
        except LocalCommandExecutionError as exc:
            raise ServerRepositorySyncError("bundle-source", str(exc)) from exc
    source = source_repository.expanduser().resolve()
    if not source.is_dir() or not (source / ".git").is_dir():
        raise ServerRepositorySyncError(
            "bundle-source",
            f"source repository is not a regular Git checkout: {source}",
        )
    origin = run_git(("remote", "get-url", "origin"))
    if origin.returncode != 0:
        raise ServerRepositorySyncError("bundle-source", "local checkout has no readable origin")
    if _github_identity(origin.stdout.strip()) != _github_identity(request.repository_url):
        raise ServerRepositorySyncError(
            "bundle-source",
            "local checkout origin does not match the requested GitHub repository",
        )
    status = run_git(("status", "--porcelain"))
    if status.returncode != 0:
        raise ServerRepositorySyncError("bundle-source", "local checkout status could not be read")
    if status.stdout:
        raise ServerRepositorySyncError("bundle-source", "local checkout is dirty")
    revision = run_git(("rev-parse", "--verify", f"{request.revision}^{{commit}}"))
    if revision.returncode != 0:
        raise ServerRepositorySyncError(
            "bundle-source",
            "requested revision is not present in the local checkout",
        )
    refs = run_git(
        (
            "for-each-ref",
            "--format=%(refname)",
            "--points-at",
            request.revision,
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        )
    )
    bundle_ref = next((line.strip() for line in refs.stdout.splitlines() if line.strip()), "")
    if refs.returncode != 0 or not bundle_ref:
        raise ServerRepositorySyncError(
            "bundle-source",
            "requested revision is not named by a local ref; refusing an ambiguous bundle",
        )
    return bundle_ref


class SSHGitBundleRepositorySynchronizer:
    """Synchronize an exact local Git object graph without remote GitHub fetch.

    The controller creates and verifies a bundle from a clean local checkout,
    uploads it through the profile-bound transfer port, and asks the server to
    import it only when the target still matches the observed base state. The
    remote bundle uses the repository synchronizer's staging name so residue is
    visible to the existing status/reconciliation contract.
    """

    def __init__(
        self,
        connection: ServerConnectionPort,
        transfer: ServerFileTransferPort,
        local_commands: LocalCommandRunnerPort,
        *,
        repository_root: str,
        profile_digest: str = "",
    ) -> None:
        if connection.profile.server_id != transfer.profile.server_id:
            raise ValueError("bundle synchronizer connection and transfer identities differ")
        if not repository_root.startswith("/") or repository_root == "/":
            raise ValueError("repository_root must be a non-root absolute POSIX path")
        self._connection = connection
        self._transfer = transfer
        self._local_commands = local_commands
        self._repository_root = posixpath.normpath(repository_root)
        self._profile_digest = profile_digest

    def _inspect_target(
        self,
        request: ServerRepositorySyncRequest,
        *,
        bundle_path: str,
    ) -> ServerRepositoryStatus:
        status = SSHGitRepositorySynchronizer(
            self._connection,
            repository_root=self._repository_root,
            profile_digest=self._profile_digest,
        ).inspect(
            request.repository_name,
            staging_revision=request.revision,
            interactive=False,
        )
        if not status.exists or status.target_kind != "git":
            raise ServerRepositorySyncError(
                "preflight",
                "bundle synchronization requires an existing Git checkout",
            )
        if status.origin != request.repository_url:
            raise ServerRepositorySyncError("preflight", "remote checkout origin does not match request")
        if status.dirty:
            raise ServerRepositorySyncError("preflight", "remote checkout is dirty")
        if status.staging_exists:
            raise ServerRepositorySyncError("preflight", f"remote bundle staging path already exists: {bundle_path}")
        return status

    def inspect(
        self,
        repository_name: str,
        *,
        staging_revision: str | None = None,
        interactive: bool = False,
    ) -> ServerRepositoryStatus:
        return SSHGitRepositorySynchronizer(
            self._connection,
            repository_root=self._repository_root,
            profile_digest=self._profile_digest,
        ).inspect(
            repository_name,
            staging_revision=staging_revision,
            interactive=interactive,
        )

    def _run_local_git(
        self,
        source_repository: Path,
        arguments: tuple[str, ...],
    ) -> LocalCommandResult:
        try:
            return self._local_commands.run(
                ("git", *arguments),
                cwd=source_repository,
                timeout_seconds=_LOCAL_GIT_TIMEOUT_SECONDS,
            )
        except LocalCommandExecutionError as exc:
            raise ServerRepositorySyncError("bundle-source", str(exc)) from exc

    def sync(
        self,
        request: ServerRepositorySyncRequest,
        *,
        source_repository: str | Path,
        interactive: bool = False,
    ) -> ServerRepositorySyncReceipt:
        if interactive:
            raise ValueError("bundle synchronization is unattended and cannot allocate a TTY")
        source = Path(source_repository).expanduser().resolve()
        bundle_ref = _require_local_git(self._local_commands, source, request)
        target = posixpath.join(self._repository_root, request.repository_name)
        bundle_path = target + ".staging-" + request.revision[:12]
        with tempfile.TemporaryDirectory(prefix="noetrium-git-bundle-") as temporary:
            bundle = Path(temporary) / f"{request.repository_name}-{request.revision}.bundle"
            created = self._run_local_git(source, ("bundle", "create", str(bundle), bundle_ref))
            if created.returncode != 0 or not bundle.is_file():
                detail = (created.stderr or created.stdout).strip().splitlines()
                raise ServerRepositorySyncError(
                    "bundle-source",
                    detail[0] if detail else "local git bundle creation failed",
                )
            verified = self._run_local_git(source, ("bundle", "verify", str(bundle)))
            if verified.returncode != 0:
                raise ServerRepositorySyncError("bundle-source", "local git bundle verification failed")

            base = self._inspect_target(request, bundle_path=bundle_path)
            transfer = self._transfer.upload(
                str(bundle),
                bundle_path,
                interactive=False,
            )
            if not transfer.succeeded:
                raise ServerRepositorySyncError("bundle-transfer", "local Git bundle upload failed")

            target_q = _shell(target)
            bundle_q = _shell(bundle_path)
            bundle_ref_q = _shell(bundle_ref)
            url_q = _shell(request.repository_url)
            base_q = _shell(base.head or "")
            revision_q = _shell(request.revision)
            command = (
                "set -eu; "
                f"target={target_q}; bundle={bundle_q}; bundle_ref={bundle_ref_q}; expected_base={base_q}; revision={revision_q}; "
                "cleanup() { rm -f -- \"$bundle\"; }; trap cleanup EXIT HUP INT TERM; "
                "test -d \"$target/.git\"; "
                "test \"$(git -C \"$target\" rev-parse HEAD)\" = \"$expected_base\"; "
                "test -z \"$(git -C \"$target\" status --porcelain)\"; "
                f"test \"$(git -C \"$target\" remote get-url origin)\" = {url_q}; "
                "git -C \"$target\" fetch --no-tags \"$bundle\" \"$bundle_ref\"; "
                "git -C \"$target\" rev-parse --verify \"$revision^{commit}\" >/dev/null; "
                "git -C \"$target\" checkout --detach \"$revision\"; "
                "test \"$(git -C \"$target\" rev-parse HEAD)\" = \"$revision\"; "
                "test -z \"$(git -C \"$target\" status --porcelain)\""
            )
            result = self._connection.execute(
                command,
                interactive=False,
                effect=ServerOperationEffect.MUTATION,
                timeout_seconds=self._connection.profile.repository_timeout_seconds,
            )
            if not result.succeeded:
                raise ServerRepositorySyncError(
                    "bundle-import",
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


__all__ = ["SSHGitBundleRepositorySynchronizer"]
