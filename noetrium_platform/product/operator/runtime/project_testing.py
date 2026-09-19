from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

from noetrium_platform.product.operator.api import (
    ProjectTestReceipt,
    ProjectTestStage,
    ProjectTestStageReceipt,
)
from noetrium_platform.product.operator.runtime.project_subprocess import (
    isolated_environment,
    isolated_module_command,
)

_TIMEOUT_SECONDS = 120


def _run_stage(
    stage: ProjectTestStage,
    command: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> ProjectTestStageReceipt:
    try:
        completed = subprocess.run(
            command, cwd=cwd, env=environment, check=False,
            timeout=_TIMEOUT_SECONDS, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
    return ProjectTestStageReceipt(stage, command, exit_code)


def _build_install_command(root: Path, install_root: Path) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-deps",
        "--target",
        str(install_root),
        str(root),
    )


def test_project(project_root: Path) -> ProjectTestReceipt:
    root = project_root.expanduser().absolute()
    if not (root / "pyproject.toml").is_file():
        raise ValueError("project test requires generated pyproject.toml")
    if not (root / "tests").is_dir() or not (root / "src").is_dir():
        raise ValueError("project test requires generated src/ and tests/ directories")
    environment = isolated_environment()
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PIP_NO_INPUT"] = "1"
    with tempfile.TemporaryDirectory(prefix="noetrium-project-test-") as td:
        install_root = Path(td) / "site-packages"
        install_root.mkdir()
        build_command = _build_install_command(root, install_root)
        build = _run_stage(
            ProjectTestStage.BUILD_INSTALL,
            build_command,
            cwd=root,
            environment=environment,
        )
        if not build.passed:
            return ProjectTestReceipt(str(root), (build,))
        contract_command = isolated_module_command(
            "unittest",
            ("discover", "-s", "tests", "-p", "test_*.py"),
            project_src=install_root,
        )
        contract = _run_stage(
            ProjectTestStage.CONTRACT_TEST,
            contract_command,
            cwd=root,
            environment=environment,
        )
        return ProjectTestReceipt(str(root), (build, contract))


__all__ = ["test_project"]
