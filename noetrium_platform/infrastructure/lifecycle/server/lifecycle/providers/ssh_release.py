from __future__ import annotations

from pathlib import Path
import shlex

from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerConnectionPort,
    ServerFileTransferPort,
)
from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect

from ..api import (
    ServerReleaseDeploymentError,
    ServerReleaseDeploymentPort,
    ServerReleaseDeploymentReceipt,
    ServerReleaseDeploymentRequest,
)


def _quote(value: str) -> str:
    return shlex.quote(value)


def _extract_command(request: ServerReleaseDeploymentRequest, *, python_executable: str) -> str:
    archive = request.layout.upload_path(request.release_digest)
    releases_root = request.layout.releases_root
    release = request.layout.release_path(request.release_digest)
    digest = request.release_digest
    script = (
        "import hashlib, os, pathlib, shutil, tempfile, zipfile\n"
        f"archive = {archive!r}\n"
        f"releases_root = {releases_root!r}\n"
        f"release = {release!r}\n"
        f"expected = {digest!r}\n"
        "actual = hashlib.sha256(pathlib.Path(archive).read_bytes()).hexdigest()\n"
        "if actual != expected:\n"
        "    raise SystemExit('archive digest mismatch')\n"
        "staging = pathlib.Path(tempfile.mkdtemp(prefix='.' + expected + '.staging-', dir=releases_root))\n"
        "published = False\n"
        "try:\n"
        "    root = os.path.abspath(staging)\n"
        "    with zipfile.ZipFile(archive) as archive_file:\n"
        "        for info in archive_file.infolist():\n"
        "            target = os.path.abspath(os.path.join(root, info.filename))\n"
        "            if os.path.commonpath((root, target)) != root:\n"
        "                raise SystemExit('release archive path traversal')\n"
        "        archive_file.extractall(root)\n"
        "    if not pathlib.Path(staging, 'RELEASE_MANIFEST.json').is_file():\n"
        "        raise SystemExit('release manifest missing')\n"
        "    if not pathlib.Path(staging, 'RELEASE_EVIDENCE.json').is_file():\n"
        "        raise SystemExit('release evidence missing')\n"
        "    pathlib.Path(staging, '.release-package.sha256').write_text(expected + '\\n', encoding='ascii')\n"
        "    os.rename(staging, release)\n"
        "    published = True\n"
        "    os.unlink(archive)\n"
        "except BaseException:\n"
        "    if not published:\n"
        "        shutil.rmtree(staging, ignore_errors=True)\n"
        "    raise\n"
    )
    return f"{_quote(python_executable)} -c {_quote('exec(' + repr(script) + ')')}"


class SSHServerReleasePublisher(ServerReleaseDeploymentPort):
    """Publish one exact release archive through injected SSH identity ports."""

    def __init__(
        self,
        connection: ServerConnectionPort,
        transfer: ServerFileTransferPort,
        *,
        python_executable: str,
    ) -> None:
        if connection.profile.server_id != transfer.profile.server_id:
            raise ValueError("release publisher connection and transfer server identities differ")
        if not python_executable.startswith("/") or any(
            char in python_executable for char in "\x00\r\n"
        ):
            raise ValueError("release publisher python_executable must be an absolute remote path")
        self._connection = connection
        self._transfer = transfer
        self._python_executable = python_executable

    def _prepare_command(self, request: ServerReleaseDeploymentRequest) -> str:
        incoming = _quote(request.layout.incoming_root)
        releases = _quote(request.layout.releases_root)
        archive = _quote(request.layout.archive_path(request.release_digest))
        upload = _quote(request.layout.upload_path(request.release_digest))
        release = _quote(request.layout.release_path(request.release_digest))
        marker = _quote(request.layout.release_path(request.release_digest) + "/.release-package.sha256")
        digest = _quote(request.release_digest)
        return (
            "set -eu; "
            f"mkdir -p -- {incoming} {releases}; "
            f"if [ -f {marker} ] && [ \"$(tr -d '[:space:]' < {marker})\" = {digest} ]; then printf 'already-published\\n'; exit 0; fi; "
            f"if [ -e {release} ]; then printf 'release-path-conflict\\n' >&2; exit 23; fi; "
            f"rm -f -- {archive} {upload}"
        )

    def publish(
        self,
        request: ServerReleaseDeploymentRequest,
        *,
        interactive: bool = False,
    ) -> ServerReleaseDeploymentReceipt:
        local = request.local_package
        if not local.is_file():
            raise ServerReleaseDeploymentError("validate", "local release package is not a regular file")
        preparation = self._connection.execute(
            self._prepare_command(request),
            interactive=interactive,
            effect=ServerOperationEffect.MUTATION,
        )
        if not preparation.succeeded:
            raise ServerReleaseDeploymentError("prepare", "remote release layout is not publishable")
        if "already-published" in preparation.stdout.splitlines():
            return ServerReleaseDeploymentReceipt(
                self._connection.profile.server_id,
                request.release_digest,
                request.layout.archive_path(request.release_digest),
                request.layout.release_path(request.release_digest),
                False,
                preparation,
                None,
                None,
            )
        transfer = self._transfer.upload(
            str(local),
            request.layout.upload_path(request.release_digest),
            interactive=interactive,
        )
        if not transfer.succeeded:
            raise ServerReleaseDeploymentError("transfer", "release package upload failed")
        finalization = self._connection.execute(
            _extract_command(request, python_executable=self._python_executable),
            interactive=interactive,
            effect=ServerOperationEffect.MUTATION,
        )
        if not finalization.succeeded:
            raise ServerReleaseDeploymentError("finalize", "remote release verification or publication failed")
        return ServerReleaseDeploymentReceipt(
            self._connection.profile.server_id,
            request.release_digest,
            request.layout.archive_path(request.release_digest),
            request.layout.release_path(request.release_digest),
            True,
            preparation,
            transfer,
            finalization,
        )


__all__ = ["SSHServerReleasePublisher"]
