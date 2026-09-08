from __future__ import annotations

import math
import shutil

from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError
from noetrium_platform.infrastructure.resources.compute.api import (
    GpuDeviceStatus,
    GpuProcessStatus,
    GpuRuntimeSnapshot,
)


class NvidiaSmiGpuRuntimeObserver:
    """Best-effort operational GPU view through the shared process authority.

    GPU observation is deliberately not an admission gate, but its child-process
    lifetime still belongs to structured concurrency.  Both nvidia-smi queries
    therefore share the process task-group budget and async subprocess watcher.
    """

    def __init__(
        self,
        command_runner: LocalCommandRunnerPort,
        *,
        executable: str = "nvidia-smi",
        command_timeout_seconds: float = 5.0,
    ) -> None:
        if not math.isfinite(float(command_timeout_seconds)) or command_timeout_seconds <= 0:
            raise ValueError("nvidia-smi command timeout must be finite and positive")
        self._command_runner = command_runner
        self._executable = executable
        self._command_timeout_seconds = float(command_timeout_seconds)

    def _run(self, argv: tuple[str, ...]):
        try:
            completed = self._command_runner.run(
                argv,
                timeout_seconds=self._command_timeout_seconds,
            )
        except (LocalCommandStartError, LocalCommandTimeoutError, OSError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout

    def snapshot(self) -> GpuRuntimeSnapshot:
        executable = shutil.which(self._executable)
        if executable is None:
            return GpuRuntimeSnapshot(False, detail="nvidia-smi-unavailable")
        devices = self._devices(executable)
        if devices is None:
            return GpuRuntimeSnapshot(False, detail="nvidia-smi-query-failed")
        processes = self._processes(executable)
        return GpuRuntimeSnapshot(True, devices=devices, processes=processes)

    def _devices(self, executable: str) -> tuple[GpuDeviceStatus, ...] | None:
        stdout = self._run((
            executable,
            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ))
        if stdout is None:
            return None
        values: list[GpuDeviceStatus] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            row = [item.strip() for item in line.split(",", 6)]
            if len(row) != 7:
                continue
            try:
                values.append(GpuDeviceStatus(row[0], row[1], row[2], int(row[3]), int(row[4]), int(row[5]), int(row[6])))
            except ValueError:
                continue
        return tuple(values)

    def _processes(self, executable: str) -> tuple[GpuProcessStatus, ...]:
        stdout = self._run((
            executable,
            "--query-compute-apps=pid,gpu_uuid,used_gpu_memory,process_name",
            "--format=csv,noheader,nounits",
        ))
        if stdout is None:
            return ()
        values: list[GpuProcessStatus] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            row = [item.strip() for item in line.split(",", 3)]
            if len(row) != 4:
                continue
            try:
                values.append(GpuProcessStatus(int(row[0]), row[1], int(row[2]), row[3]))
            except ValueError:
                continue
        return tuple(values)


__all__ = ["NvidiaSmiGpuRuntimeObserver"]
