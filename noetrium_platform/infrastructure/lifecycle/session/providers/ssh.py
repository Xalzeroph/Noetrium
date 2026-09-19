from __future__ import annotations

from collections.abc import Mapping
import re
import shlex

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionPort
from noetrium_platform.infrastructure.lifecycle.session.runtime.tmux_contracts import TmuxCommandResult, TmuxCommandRunner
from noetrium_platform.infrastructure.lifecycle.session.runtime.tmux_identity import TmuxTransportIdentity
from noetrium_platform.infrastructure.lifecycle.session.runtime.tmux_transport import TmuxPersistentSessionControl


def _validated_environment(
    values: Mapping[str, str] | tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    source = values.items() if isinstance(values, Mapping) else values
    entries = tuple(sorted((str(key), str(value)) for key, value in source))
    for key, value in entries:
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ValueError("remote tmux environment contains an unsafe entry")
    return entries


class SSHRemoteTmuxCommandRunner(TmuxCommandRunner):
    """Run the generic tmux codec through the injected SSH command port."""

    def __init__(
        self,
        connection: ServerConnectionPort,
        *,
        remote_env_executable: str,
        base_environment: Mapping[str, str] | tuple[tuple[str, str], ...],
        interactive: bool = False,
    ) -> None:
        if not remote_env_executable.startswith("/"):
            raise ValueError("remote environment executable must be absolute")
        self.connection = connection
        self.remote_env_executable = remote_env_executable
        self.base_environment = _validated_environment(base_environment)
        self.interactive = interactive

    def command(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str] | None = None,
    ) -> str:
        merged = dict(self.base_environment)
        if environment is not None:
            merged.update(environment)
        remote_argv = (
            self.remote_env_executable,
            "-i",
            *(f"{key}={value}" for key, value in _validated_environment(merged)),
            *argv,
        )
        return shlex.join(remote_argv)

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        effect: str = "unknown",
    ) -> TmuxCommandResult:
        command = self.command(argv, environment=environment)
        result = self.connection.execute(command, interactive=self.interactive, effect=effect)
        return TmuxCommandResult(result.return_code, result.stdout, result.stderr)

    def attest_binary(
        self,
        *,
        digest_executable: str,
        binary_path: str,
        expected_digest: str,
        interactive: bool = False,
    ) -> None:
        command = self.command((digest_executable, "--", binary_path))
        result = self.connection.execute(command, interactive=interactive, effect="observation")
        if result.return_code != 0:
            raise RuntimeError("remote tmux binary attestation command failed")
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[* ]?.*\s*", result.stdout.strip())
        if match is None or match.group(1).lower() != expected_digest.lower():
            raise RuntimeError("remote tmux binary identity differs from the frozen server profile")


class SSHRemoteTmuxSessionControl(TmuxPersistentSessionControl):
    """Persistent-session control backed by one attested remote tmux binary."""

    def __init__(
        self,
        connection: ServerConnectionPort,
        *,
        tmux_executable: str,
        binary_identity_digest: str,
        server_label: str,
        config_file: str,
        socket_directory: str,
        remote_env_executable: str,
        sha256sum_executable: str,
        session_environment: Mapping[str, str],
        interactive: bool = False,
    ) -> None:
        identity = TmuxTransportIdentity.from_remote_attestation(
            executable=tmux_executable,
            binary_sha256=binary_identity_digest,
            server_label=server_label,
            config_file=config_file,
            socket_directory=socket_directory,
        )
        runner = SSHRemoteTmuxCommandRunner(
            connection,
            remote_env_executable=remote_env_executable,
            base_environment=session_environment,
            interactive=interactive,
        )
        runner.attest_binary(
            digest_executable=sha256sum_executable,
            binary_path=tmux_executable,
            expected_digest=binary_identity_digest,
            interactive=interactive,
        )
        super().__init__(
            tmux_executable=tmux_executable,
            server_label=server_label,
            config_file=config_file,
            environment_executable=remote_env_executable,
            socket_directory=socket_directory,
            runner=runner,
            transport_identity=identity,
        )
        self._connection = connection
        self._remote_runner = runner

    def attach_argv(self, session_name: str) -> tuple[str, ...]:
        command = self._remote_runner.command(self.commands.attach_argv(session_name))
        return self._connection.interactive_argv(command, allocate_tty=True)


__all__ = ["SSHRemoteTmuxCommandRunner", "SSHRemoteTmuxSessionControl"]
