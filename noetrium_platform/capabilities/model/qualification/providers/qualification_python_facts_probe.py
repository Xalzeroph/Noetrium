"""Target-Python facts for deployment qualification."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from noetrium_platform.capabilities.model.qualification.api import PythonRuntimeFacts

CommandRun = Callable[[tuple[str, ...], float], tuple[int, str, str]]
_INFO_FIELDS = frozenset({
    "version",
    "site_packages",
    "torch_version",
    "kernel_architectures",
    "native_library_names",
    "python_abi",
    "platform_tag",
})


@dataclass(frozen=True, slots=True)
class _PythonProbeInfo:
    version: str
    site_packages: str | None
    torch_version: str | None
    kernel_architectures: tuple[str, ...]
    native_library_names: tuple[str, ...]
    python_abi: str | None
    platform_tag: str | None


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ValueError(f"{field} must be a JSON list")
    if any(type(item) is not str or not item.strip() for item in value):
        raise ValueError(f"{field} must contain only non-empty strings")
    return tuple(value)


def _decode_info(output: str) -> _PythonProbeInfo:
    payload = json.loads(output.strip().splitlines()[-1])
    if type(payload) is not dict:
        raise ValueError("probe payload root must be a JSON object")
    if frozenset(payload) != _INFO_FIELDS:
        raise ValueError("probe payload field set mismatch")
    return _PythonProbeInfo(
        version=_text(payload["version"], "version") or "",
        site_packages=_text(payload["site_packages"], "site_packages", optional=True),
        torch_version=_text(payload["torch_version"], "torch_version", optional=True),
        kernel_architectures=_strings(payload["kernel_architectures"], "kernel_architectures"),
        native_library_names=_strings(payload["native_library_names"], "native_library_names"),
        python_abi=_text(payload["python_abi"], "python_abi", optional=True),
        platform_tag=_text(payload["platform_tag"], "platform_tag", optional=True),
    )


class PythonFactsProbe:
    """Capture read-only interpreter and installed-runtime facts."""

    def __init__(self, run: CommandRun) -> None:
        self._run = run

    def capture(self, executable: Path, timeout: float) -> tuple[PythonRuntimeFacts, list[str]]:
        errors: list[str] = []
        info_code = (
            "import glob, importlib.metadata, json, pathlib, sys, sysconfig\n"
            "p = sysconfig.get_paths().get('purelib')\n"
            "a = sorted({pathlib.Path(x).parent.name for x in glob.glob((p or '') + '/sgl_kernel/sm*/common_ops.*')})\n"
            "patterns = tuple((p or '') + '/**/' + name for name in ('libcudart.so*', 'libnvrtc.so*', 'libcublas.so*', 'libnccl.so*'))\n"
            "native = sorted({pathlib.Path(x).name for pattern in patterns for x in glob.glob(pattern, recursive=True)})\n"
            "t = next((d.version for d in importlib.metadata.distributions() if (d.metadata.get('Name') or '').lower() == 'torch'), None)\n"
            "print(json.dumps({'version': '.'.join(map(str, sys.version_info[:3])), 'site_packages': p, 'torch_version': t, 'kernel_architectures': a, 'native_library_names': native, 'python_abi': getattr(sys.implementation, 'cache_tag', None), 'platform_tag': sysconfig.get_platform()}))\n"
        )
        code, out, _ = self._run((str(executable), "-c", info_code), timeout)
        info: _PythonProbeInfo | None = None
        if code == 0:
            try:
                info = _decode_info(out)
            except (json.JSONDecodeError, IndexError, ValueError) as exc:
                errors.append(f"Python capability probe returned invalid typed facts: {exc}")
        else:
            errors.append("Python capability probe failed")
        torch_cuda_version = None
        torch_code, torch_out, _ = self._run(
            (str(executable), "-c", "import torch; print(torch.version.cuda or '')"),
            timeout,
        )
        if torch_code == 0:
            torch_cuda_version = next((line.strip() for line in torch_out.splitlines() if line.strip()), None)

        code, out, _ = self._run((str(executable), "-m", "pip", "--version"), timeout)
        pip_version = out.strip() if code == 0 and out.strip() else None
        if pip_version is None:
            errors.append("selected Python interpreter has no pip")

        code, _, _ = self._run((str(executable), "-m", "ensurepip", "--version"), timeout)
        ensurepip = code == 0
        code, _, _ = self._run((str(executable), "-c", "import venv; print('ok')"), timeout)
        venv = code == 0 and ensurepip
        if not venv:
            errors.append("selected Python interpreter has no usable venv bootstrap")

        return PythonRuntimeFacts(
            executable=str(executable),
            version=info.version if info is not None else "unknown",
            pip_version=pip_version,
            ensurepip_available=ensurepip,
            venv_available=venv,
            site_packages=info.site_packages if info is not None else None,
            torch_version=info.torch_version if info is not None else None,
            torch_cuda_version=torch_cuda_version,
            kernel_architectures=info.kernel_architectures if info is not None else (),
            errors=tuple(errors),
            python_abi=info.python_abi if info is not None else None,
            platform_tag=info.platform_tag if info is not None else None,
            native_library_names=info.native_library_names if info is not None else (),
        ), errors


__all__ = ["PythonFactsProbe"]
