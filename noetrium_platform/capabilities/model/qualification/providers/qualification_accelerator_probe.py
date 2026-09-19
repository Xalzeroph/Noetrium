"""Read-only accelerator and GPU-fabric facts for model qualification."""

from __future__ import annotations

import csv
from pathlib import Path
import re
from typing import Callable

from noetrium_platform.capabilities.model.qualification.api import (
    CudaFacts, DeploymentQualificationRequest, GpuCapabilityFacts, GpuFabricFacts, PythonRuntimeFacts,
)

CommandRun = Callable[[tuple[str, ...], float], tuple[int, str, str]]


class AcceleratorFactsProbe:
    """Capture CUDA, GPU and fabric facts through a bounded command runner."""

    def __init__(self, run: CommandRun) -> None:
        self._run = run
    def cuda(self, timeout: float) -> tuple[CudaFacts, list[str]]:
        errors: list[str] = []
        driver = None
        driver_cuda = None
        nvml = None
        code, out, _ = self._run(
            ("nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader,nounits"),
            timeout,
        )
        if code == 0:
            driver = next((line.strip() for line in out.splitlines() if line.strip()), None)
        else:
            errors.append("nvidia-smi driver query failed")
        code, out, err = self._run(("nvidia-smi",), timeout)
        if code == 0:
            match = re.search(r"CUDA Version:\s*([^\s]+)", out)
            driver_cuda = match.group(1) if match else None
            nvml_match = re.search(r"NVIDIA Management Library Version:\s*([^\s]+)", out)
            nvml = nvml_match.group(1) if nvml_match else None
        else:
            errors.append("nvidia-smi summary query failed")
        code, out, err = self._run(("nvcc", "--version"), timeout)
        toolkit = None
        if code == 0:
            match = re.search(r"release\s+([0-9.]+)", out)
            toolkit = match.group(1) if match else None
        else:
            errors.append("nvcc toolkit query unavailable")
        nvrtc_paths = []
        for root in (Path("/usr/local"), Path("/usr/lib")):
            if not root.exists():
                continue
            nvrtc_paths.extend(root.glob("cuda*/lib*/libnvrtc.so.*"))
            nvrtc_paths.extend(root.glob("lib*/libnvrtc.so.*"))
        nvrtc = tuple(
            sorted(
                {
                    match.group(1)
                    for path in nvrtc_paths
                    if (match := re.search(r"libnvrtc\.so\.([0-9.]+)$", path.name))
                }
            )
        )
        runtime_libraries = self._cuda_runtime_libraries(timeout)
        return CudaFacts(driver, driver_cuda, toolkit, nvrtc, (), nvml, runtime_libraries), errors

    def _cuda_runtime_libraries(self, timeout: float) -> tuple[str, ...]:
        code, out, _ = self._run(("ldconfig", "-p"), timeout)
        if code != 0:
            return ()
        values = {
            match.group(1)
            for line in out.splitlines()
            if (match := re.search(r"lib(?:cudart|cuda)\.so\.([0-9.]+)", line))
        }
        return tuple(sorted(values))

    def gpus(
        self,
        request: DeploymentQualificationRequest,
        python: PythonRuntimeFacts,
        timeout: float,
    ) -> tuple[tuple[GpuCapabilityFacts, ...], list[str]]:
        errors: list[str] = []
        query = (
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.total,memory.free,pci.bus_id,compute_cap,power.limit",
            "--format=csv,noheader,nounits",
        )
        code, out, err = self._run(query, timeout)
        query_mode = "extended" if code == 0 else "compute"
        if code != 0:
            errors.append("nvidia-smi GPU capability query failed")
            code, out, err = self._run(
                (
                    "nvidia-smi",
                    "--query-gpu=index,uuid,name,memory.total,memory.free,compute_cap",
                    "--format=csv,noheader,nounits",
                ),
                timeout,
            )
            query_mode = "compute" if code == 0 else "basic"
        if code != 0:
            code, out, err = self._run(
                (
                    "nvidia-smi",
                    "--query-gpu=index,uuid,name,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ),
                timeout,
            )
        if code != 0:
            return (), errors
        torch_caps = self._torch_capabilities(request.python_executable, timeout)
        values: list[GpuCapabilityFacts] = []
        for row_index, row in enumerate(csv.reader(out.splitlines())):
            row = [value.strip() for value in row]
            if len(row) < 5:
                continue
            pci_bus_id = None
            power_limit = None
            cap_index = 5
            if query_mode == "extended":
                pci_bus_id = row[5] if len(row) > 5 and row[5] not in {"N/A", "[Not Supported]"} else None
                cap_index = 6
                if len(row) > 7 and row[7] not in {"N/A", "[Not Supported]"}:
                    try:
                        power_limit = float(row[7])
                    except ValueError:
                        errors.append(f"invalid GPU power limit row {row_index}")
            cap = row[cap_index] if len(row) > cap_index and row[cap_index] not in {"N/A", "[Not Supported]"} else None
            if cap is None and row_index < len(torch_caps):
                cap = torch_caps[row_index]
            try:
                values.append(
                    GpuCapabilityFacts(
                        row[0],
                        row[1],
                        row[2],
                        int(row[3]),
                        int(row[4]),
                        cap,
                        pci_bus_id,
                        self._pci_numa_node(pci_bus_id),
                        power_limit,
                    )
                )
            except ValueError:
                errors.append(f"invalid nvidia-smi GPU row {row_index}")
        return tuple(values), errors

    @staticmethod
    def _pci_numa_node(pci_bus_id: str | None) -> int | None:
        if not pci_bus_id:
            return None
        normalized = pci_bus_id
        if re.fullmatch(r"[0-9a-fA-F]{8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]", normalized):
            normalized = normalized[4:]
        path = Path("/sys/bus/pci/devices") / normalized / "numa_node"
        try:
            value = path.read_text("utf-8", errors="replace").strip()
            return int(value) if value else None
        except (OSError, ValueError):
            return None

    def _torch_capabilities(self, executable: Path, timeout: float) -> tuple[str, ...]:
        code, out, err = self._run(
            (str(executable), "-c", "import torch; print('\\n'.join('%d.%d'%torch.cuda.get_device_capability(i) for i in range(torch.cuda.device_count())))"),
            timeout,
        )
        return tuple(line.strip() for line in out.splitlines() if re.fullmatch(r"\d+\.\d+", line.strip())) if code == 0 else ()

    def fabric(self, executable: Path, timeout: float) -> tuple[GpuFabricFacts, list[str]]:
        errors: list[str] = []
        code, out, _ = self._run(("nvidia-smi", "topo", "-m"), timeout)
        topology = (
            tuple(
                re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip()
                for line in out.splitlines()
                if line.strip()
            )
            if code == 0
            else ()
        )
        if not topology:
            errors.append("NVIDIA GPU topology query unavailable")

        nccl_version = None
        code, out, _ = self._run(
            (
                str(executable),
                "-c",
                "import torch; value = getattr(torch.cuda.nccl, 'version', lambda: None)(); print(value or '')",
            ),
            timeout,
        )
        if code == 0:
            nccl_version = next((line.strip() for line in out.splitlines() if line.strip()), None)
        if not nccl_version:
            errors.append("target Python NCCL version unavailable")

        nccl_library = None
        code, out, _ = self._run(("ldconfig", "-p"), timeout)
        if code == 0:
            nccl_library = next(
                (
                    line.strip()
                    for line in out.splitlines()
                    if "libnccl.so" in line and "=>" in line
                ),
                None,
            )
        if not nccl_library:
            errors.append("system NCCL library identity unavailable")
        return GpuFabricFacts(topology, nccl_version, nccl_library, tuple(errors)), errors


__all__ = ["AcceleratorFactsProbe"]
