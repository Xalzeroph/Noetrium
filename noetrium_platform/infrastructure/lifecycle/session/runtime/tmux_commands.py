from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex

from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


@dataclass(frozen=True, slots=True)
class TmuxCommandCodec:
    executable: str = "/usr/bin/tmux"
    server_label: str = "noetrium"
    config_file: str = "/dev/null"
    environment_executable: str = "/usr/bin/env"

    def __post_init__(self) -> None:
        if not is_absolute_target_path(self.executable):
            raise ValueError("tmux executable must be absolute")
        if not _LABEL_RE.fullmatch(self.server_label):
            raise ValueError("tmux server label must be a safe non-empty identifier")
        if not is_absolute_target_path(self.config_file):
            raise ValueError("tmux config file must be absolute")
        if not is_absolute_target_path(self.environment_executable):
            raise ValueError("environment executable must be absolute")

    def argv(self, *args: str) -> tuple[str, ...]:
        return (self.executable, "-f", self.config_file, "-L", self.server_label, *args)

    def pane_command(self, spec: PersistentSessionSpec) -> str:
        env_argv = (
            self.environment_executable,
            "-i",
            *(f"{key}={value}" for key, value in spec.process_environment),
            *spec.command_argv,
        )
        return "exec " + shlex.join(env_argv)

    def inspect_argv(self, session_name: str) -> tuple[str, ...]:
        return self.argv(
            "display-message",
            "-p",
            "-t",
            f"={session_name}:0.0",
            r"#{session_name}\t#{pane_pid}\t#{pane_dead}\t#{pane_start_command}\t#{pane_current_path}",
        )

    def create_argv(self, spec: PersistentSessionSpec) -> tuple[str, ...]:
        return self.argv(
            "new-session",
            "-d",
            "-s",
            spec.session_name,
            "-c",
            spec.cwd,
            self.pane_command(spec),
        )

    def terminate_argv(self, session_name: str) -> tuple[str, ...]:
        return self.argv("kill-session", "-t", f"={session_name}")

    def attach_argv(self, session_name: str) -> tuple[str, ...]:
        return self.argv("attach-session", "-t", f"={session_name}")


__all__ = ["TmuxCommandCodec"]
