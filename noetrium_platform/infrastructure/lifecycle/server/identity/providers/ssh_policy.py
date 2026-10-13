from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..api import ServerConnectionProfile


@dataclass(frozen=True, slots=True)
class OpenSSHArgumentPolicy:
    """Pure argv policy shared by SSH command and SCP transfer providers."""

    profile: ServerConnectionProfile

    def _transport_options(self, *, interactive: bool, scp: bool) -> list[str]:
        option_flag = "-P" if scp else "-p"
        argv = [
            option_flag,
            str(self.profile.port),
            "-o",
            f"ConnectTimeout={self.profile.connect_timeout_seconds}",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
        ]
        if not interactive:
            if scp:
                argv.append("-B")
            else:
                argv.extend(("-o", "BatchMode=yes"))
            argv.extend((
                "-o", "PasswordAuthentication=no",
                "-o", "KbdInteractiveAuthentication=no",
                "-o", "NumberOfPasswordPrompts=0",
                "-o", "PreferredAuthentications=publickey",
                "-o", "GSSAPIAuthentication=no",
                "-o", "StrictHostKeyChecking=yes",
                "-o", "ControlMaster=no",
                "-o", "ControlPath=none",
            ))
        if self.profile.key_path is not None:
            argv.extend(("-i", str(self.profile.key_path)))
        if self.profile.ssh_config_path is not None:
            argv.extend(("-F", str(self.profile.ssh_config_path)))
        if self.profile.known_hosts_path is not None:
            argv.extend(("-o", f"UserKnownHostsFile={self.profile.known_hosts_path}"))
        if interactive and self.profile.control_path is not None:
            argv.extend((
                "-o", "ControlMaster=auto",
                "-o", f"ControlPersist={self.profile.control_persist_seconds}",
                "-o", f"ControlPath={self.profile.control_path}",
            ))
        return argv

    def command(self, command: str, *, interactive: bool) -> tuple[str, ...]:
        argv = [self.profile.ssh_executable, *self._transport_options(interactive=interactive, scp=False)]
        argv.extend((self.profile.destination, command))
        return tuple(argv)

    def upload(self, scp_executable: str, local_path: Path, remote_path: str, *, interactive: bool) -> tuple[str, ...]:
        argv = [scp_executable, *self._transport_options(interactive=interactive, scp=True)]
        argv.extend((str(local_path), f"{self.profile.destination}:{remote_path}"))
        return tuple(argv)

    def download(self, scp_executable: str, remote_path: str, local_path: Path, *, interactive: bool) -> tuple[str, ...]:
        argv = [scp_executable, *self._transport_options(interactive=interactive, scp=True)]
        argv.extend((f"{self.profile.destination}:{remote_path}", str(local_path)))
        return tuple(argv)

    def prepare_control_path(self) -> None:
        if self.profile.control_path is not None:
            self.profile.control_path.parent.mkdir(parents=True, exist_ok=True)


__all__ = ["OpenSSHArgumentPolicy"]
