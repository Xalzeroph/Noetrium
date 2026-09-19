from __future__ import annotations

from collections.abc import Mapping
import os
import shutil

from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessCommandRunnerPort

from ..api import server_environment_prefix
from .ssh_connection import SSHServerConnection
from .ssh_profile import materialize_ssh_profile
from .ssh_transfer import SSHServerFileTransfer


class EnvironmentSSHServerConnectionFactory:
    def __init__(
        self,
        operating_system: OperatingSystemRoute,
        *,
        ssh_executable: str | None = None,
        process_runner: ProcessCommandRunnerPort | None = None,
    ) -> None:
        self._operating_system = operating_system
        self._ssh_executable = ssh_executable
        self._process_runner = process_runner

    def from_environment(self, server_id: str, *, environ: Mapping[str, str] | None = None) -> SSHServerConnection:
        values = os.environ if environ is None else environ
        profile = materialize_ssh_profile(server_id, values, ssh_executable=self._ssh_executable)
        return SSHServerConnection(
            profile, operating_system=self._operating_system, process_runner=self._process_runner
        )


class EnvironmentSSHServerFileTransferFactory:
    def __init__(
        self,
        operating_system: OperatingSystemRoute,
        *,
        scp_executable: str | None = None,
        process_runner: ProcessCommandRunnerPort | None = None,
    ) -> None:
        self._operating_system = operating_system
        self._scp_executable = scp_executable
        self._process_runner = process_runner

    def from_environment(self, server_id: str, *, environ: Mapping[str, str] | None = None) -> SSHServerFileTransfer:
        values = os.environ if environ is None else environ
        profile = materialize_ssh_profile(server_id, values, ssh_executable=None)
        scp_executable = self._scp_executable or values.get(
            f"{server_environment_prefix(server_id)}_SCP", ""
        ).strip() or shutil.which("scp") or "scp"
        return SSHServerFileTransfer(
            profile,
            operating_system=self._operating_system,
            scp_executable=scp_executable,
            process_runner=self._process_runner,
        )


__all__ = ["EnvironmentSSHServerConnectionFactory", "EnvironmentSSHServerFileTransferFactory"]
