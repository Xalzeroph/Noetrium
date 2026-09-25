from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from noetrium_platform.foundation.governance.architecture.repository_boundary.runtime import (
    audit_downstream_project_imports,
)
from noetrium_platform.product.operator.api import (
    ProjectCreateRequest,
    ProjectDoctorDisposition,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult
from noetrium_platform.composition.operator.project import project_doctor, project_scaffold
from noetrium_platform.composition.operator.project.project_platform_identity import (
    InstalledPlatformIdentity,
)

_FIXED_PLATFORM = InstalledPlatformIdentity("0.1.0", "a" * 64)


class _TestCommandRunner:
    def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=None if environment is None else dict(environment),
            timeout=timeout_seconds,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return LocalCommandResult(tuple(argv), completed.returncode, completed.stdout, completed.stderr)


_COMMAND_RUNNER = _TestCommandRunner()


def test_project_doctor_rejects_invalid_user_core_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    monkeypatch.setattr(
        project_doctor,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    root = tmp_path / "identity-drift"
    project_scaffold.create_project(
        ProjectCreateRequest("identity-drift", "0.1.0", root)
    )

    core = root / "src" / "identity_drift" / "core.py"
    source = core.read_text(encoding="utf-8")
    core.write_text(
        source.replace(
            "    return api.ResearchPortfolio('identity-drift', (program.freeze(),))",
            "    return object()",
        ),
        encoding="utf-8",
    )

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
        command_runner=_COMMAND_RUNNER,
    )
    checks = {row.check_id: row.disposition for row in report.checks}
    assert checks["public_import_boundary"] is ProjectDoctorDisposition.PASS
    assert checks["generated_shell"] is ProjectDoctorDisposition.PASS
    assert checks["standard_bindings"] is ProjectDoctorDisposition.BLOCKED
    assert not report.ready
