from __future__ import annotations

from dataclasses import replace
import shlex

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerConnectionPort,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerRemoteProfile


class ProfileBoundServerConnection(ServerConnectionPort):
    """Bind every direct SSH command to the declared remote runtime profile.

    Persistent operator sessions already receive ``ServerRemoteProfile``
    environment values. Direct commands must receive the same values or a
    shebang (for example npm -> node) can silently select a different system
    toolchain. The wrapper is composed once by the server-management root; it
    is not a service locator and it does not choose fallback executables.
    """

    def __init__(self, connection: ServerConnectionPort, profile: ServerRemoteProfile) -> None:
        if connection.profile.server_id != profile.server_id:
            raise ValueError("server connection and remote profile ids differ")
        self._connection = connection
        self._remote_profile = profile

    @property
    def profile(self):
        return self._connection.profile

    def _bound_command(self, command: str) -> str:
        if not command.strip():
            raise ValueError("remote command must be non-empty")
        assignments = " ".join(
            f"{shlex.quote(name)}={shlex.quote(value)}"
            for name, value in self._remote_profile.session_environment
        )
        shell = shlex.quote(self._remote_profile.operator_shell)
        return (
            f"{shlex.quote(self._remote_profile.remote_env_executable)} "
            f"{assignments} {shell} -lc {shlex.quote(command)}"
        )

    def execute(
        self,
        command: str,
        *,
        interactive: bool = False,
        effect: ServerOperationEffect = ServerOperationEffect.UNKNOWN,
        timeout_seconds: float | None = None,
    ) -> ServerCommandResult:
        kwargs = {"interactive": interactive, "effect": effect}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        result = self._connection.execute(self._bound_command(command), **kwargs)
        return replace(result, command=command)

    def interactive_argv(
        self,
        command: str,
        *,
        allocate_tty: bool = False,
    ) -> tuple[str, ...]:
        return self._connection.interactive_argv(
            self._bound_command(command),
            allocate_tty=allocate_tty,
        )

    def run_interactive(self, argv: tuple[str, ...]) -> int:
        return self._connection.run_interactive(argv)


__all__ = ["ProfileBoundServerConnection"]
