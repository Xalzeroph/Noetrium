from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LinuxProcessFacts:
    start_identity: str
    executable: str
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]
    process_group_id: int


class LinuxProcfsReader:
    """Read-only /proc view. Signal/spawn authority deliberately lives elsewhere."""

    def __init__(self, root: Path = Path("/proc")) -> None:
        self.root = root

    def _process_directory(self, pid: int) -> Path:
        """Resolve a process visible through a nested Linux PID namespace.

        Some supervised runtimes see child PIDs in their namespace while the
        mounted procfs is owned by an outer namespace.  Linux exposes both
        identities in ``status:NSpid``.  Prefer the direct path and only scan
        procfs when the direct namespace path is absent; normal hosts therefore
        retain the cheap and exact path lookup.
        """

        direct = self.root / str(pid)
        if direct.is_dir():
            return direct
        for candidate in self.root.iterdir():
            if not candidate.name.isdigit() or not candidate.is_dir():
                continue
            try:
                status = (candidate / "status").read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for line in status.splitlines():
                if not line.startswith("NSpid:"):
                    continue
                identities = line.split()[1:]
                if identities and identities[-1] == str(pid):
                    return candidate
                break
        return direct

    def path(self, pid: int, name: str = "") -> Path:
        return self._process_directory(pid) / name

    def visible_pid(self, pid: int) -> int:
        """Return the procfs PID corresponding to a namespace-local PID."""

        return int(self._process_directory(pid).name)

    @staticmethod
    def alive_pid(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _start_identity_from_directory(self, process_directory: Path) -> str:
        stat = (process_directory / "stat").read_text(encoding="utf-8")
        close = stat.rfind(")")
        if close < 0:
            raise RuntimeError("invalid /proc stat format")
        fields = stat[close + 2 :].split()
        if len(fields) <= 19:
            raise RuntimeError("/proc stat missing starttime")
        start_ticks = fields[19]
        boot_id_path = self.root / "sys/kernel/random/boot_id"
        boot_id = boot_id_path.read_text(encoding="utf-8").strip() if boot_id_path.exists() else "unknown-boot"
        return f"linux-proc:{boot_id}:{start_ticks}"

    @staticmethod
    def _cmdline_from_directory(process_directory: Path) -> tuple[str, ...]:
        raw = (process_directory / "cmdline").read_bytes()
        return tuple(part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\x00") if part)

    @staticmethod
    def _environment_from_directory(process_directory: Path) -> dict[str, str]:
        raw = (process_directory / "environ").read_bytes()
        result: dict[str, str] = {}
        for item in raw.split(b"\x00"):
            if not item:
                continue
            key, sep, value = item.partition(b"=")
            if not sep:
                continue
            result[key.decode("utf-8", errors="surrogateescape")] = value.decode("utf-8", errors="surrogateescape")
        return result

    def start_identity(self, pid: int) -> str:
        return self._start_identity_from_directory(self._process_directory(pid))

    def cmdline(self, pid: int) -> tuple[str, ...]:
        return self._cmdline_from_directory(self._process_directory(pid))

    def environment(self, pid: int) -> dict[str, str]:
        return self._environment_from_directory(self._process_directory(pid))

    def facts(self, pid: int, *, control_pid: int | None = None) -> LinuxProcessFacts:
        process_directory = self._process_directory(pid)
        return LinuxProcessFacts(
            start_identity=self._start_identity_from_directory(process_directory),
            executable=str((process_directory / "exe").resolve()),
            argv=self._cmdline_from_directory(process_directory),
            cwd=str((process_directory / "cwd").resolve()),
            environment=self._environment_from_directory(process_directory),
            process_group_id=os.getpgid(pid if control_pid is None else control_pid),
        )


__all__ = ["LinuxProcessFacts", "LinuxProcfsReader"]
