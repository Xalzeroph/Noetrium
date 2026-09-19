from __future__ import annotations

import os
from pathlib import Path
import sys

import noetrium_platform

_BOOTSTRAP_MODULE = r'''
import runpy
import sys

platform_root, project_src, module_name, *module_args = sys.argv[1:]
sys.path[:0] = [project_src, platform_root]
sys.argv = [module_name, *module_args]
runpy.run_module(module_name, run_name="__main__")
'''


def platform_import_root() -> Path:
    package_file = getattr(noetrium_platform, "__file__", None)
    if not isinstance(package_file, str) or not package_file:
        raise RuntimeError("loaded noetrium_platform package has no filesystem identity")
    return Path(package_file).resolve().parent.parent


def isolated_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def isolated_script_command(script: str, *, project_src: Path) -> tuple[str, ...]:
    if not isinstance(script, str) or not script.strip():
        raise ValueError("project subprocess script must be non-empty")
    bootstrap = (
        "import sys\n"
        "platform_root, project_src = sys.argv[1:3]\n"
        "sys.path[:0] = [project_src, platform_root]\n"
        + script
    )
    return (
        sys.executable,
        "-I",
        "-c",
        bootstrap,
        str(platform_import_root()),
        str(project_src.resolve()),
    )


def isolated_module_command(
    module_name: str,
    module_args: tuple[str, ...],
    *,
    project_src: Path,
) -> tuple[str, ...]:
    if not isinstance(module_name, str) or not module_name.strip():
        raise ValueError("project subprocess module name must be non-empty")
    if any(not isinstance(item, str) for item in module_args):
        raise TypeError("project subprocess module arguments must be text")
    return (
        sys.executable,
        "-I",
        "-c",
        _BOOTSTRAP_MODULE,
        str(platform_import_root()),
        str(project_src.resolve()),
        module_name,
        *module_args,
    )


__all__ = [
    "isolated_environment",
    "isolated_module_command",
    "isolated_script_command",
    "platform_import_root",
]
