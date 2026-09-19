from __future__ import annotations

import shlex

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionPort

from ..api import ServerReleaseLayout, ServerReleaseLayoutError


class SSHServerReleaseDirectory:
    """Remote implementation of the content-addressed release-directory port."""

    def __init__(self, connection: ServerConnectionPort, layout: ServerReleaseLayout) -> None:
        self._connection = connection
        self._layout = layout

    def require_release_dir(self, release_digest: str) -> str:
        release = self._layout.release_path(release_digest)
        command = (
            "set -eu; "
            f"test -d {shlex.quote(release)}; "
            f"test ! -L {shlex.quote(release)}; "
            f"printf 'release=%s\\n' {shlex.quote(release)}"
        )
        result = self._connection.execute(
            command,
            effect=ServerOperationEffect.OBSERVATION,
        )
        if not result.succeeded or f"release={release}" not in result.stdout.splitlines():
            raise ServerReleaseLayoutError(
                f"remote immutable release directory missing or invalid: {release}"
            )
        return release


__all__ = ["SSHServerReleaseDirectory"]
