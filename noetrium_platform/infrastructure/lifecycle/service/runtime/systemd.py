from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SystemdUnitSpec:
    unit_name: str
    description: str
    exec_start: tuple[str,...]
    working_directory: str
    environment_file: str | None = None
    restart_sec_s: int = 10
    start_limit_burst: int = 6
    start_limit_interval_s: int = 900
    timeout_start_s: int = 1900
    watchdog_s: int = 45


class SystemdRenderer:
    """Deterministic service manager adapter. It does not choose models/resources or fallback behavior."""
    @staticmethod
    def _quote(arg:str)->str:
        if "\n" in arg or "\r" in arg: raise ValueError("systemd argument contains newline")
        return '"'+arg.replace('\\','\\\\').replace('"','\\"')+'"'
    def render(self,spec:SystemdUnitSpec)->str:
        if not spec.exec_start or not spec.exec_start[0].startswith("/"): raise ValueError("systemd ExecStart executable must be absolute")
        if not spec.working_directory.startswith("/"): raise ValueError("systemd WorkingDirectory must be absolute")
        lines=[
            "[Unit]",f"Description={spec.description}",f"StartLimitIntervalSec={spec.start_limit_interval_s}",f"StartLimitBurst={spec.start_limit_burst}","After=network-online.target","Wants=network-online.target","",
            "[Service]","Type=notify","NotifyAccess=main",f"WorkingDirectory={spec.working_directory}","ExecStart="+" ".join(self._quote(x) for x in spec.exec_start),
            "Restart=on-failure","RestartPreventExitStatus=70 74 78",f"RestartSec={spec.restart_sec_s}",f"TimeoutStartSec={spec.timeout_start_s}",f"WatchdogSec={spec.watchdog_s}",
            "KillMode=control-group","TimeoutStopSec=90","LimitNOFILE=1048576","NoNewPrivileges=true",
        ]
        if spec.environment_file: lines.append(f"EnvironmentFile={spec.environment_file}")
        lines += ["","[Install]","WantedBy=multi-user.target",""]
        return "\n".join(lines)
