from __future__ import annotations

import re
from pathlib import Path
import tomllib

from noetrium_platform.foundation.governance.architecture.repository_boundary.api import (
    RepositoryBoundaryAuditor,
)
from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandRunnerPort,
    LocalCommandStartError,
    LocalCommandTimeoutError,
)
from noetrium_platform.product.operator.api import (
    ProjectDoctorCheck,
    ProjectDoctorDisposition,
    ProjectDoctorReport,
    project_template_revision,
)
from noetrium_platform.composition.operator.project.project_layout import project_package_name
from noetrium_platform.composition.operator.project.project_platform_identity import (
    installed_platform_identity,
)
from noetrium_platform.composition.operator.project.research_project_codegen import (
    render_generated_test_module,
    render_research_module,
)
from noetrium_platform.composition.operator.project.project_subprocess import (
    isolated_environment,
    isolated_script_command,
)
from noetrium_platform.foundation.portfolio.api import (
    ProjectManifest,
    ProjectManifestDecodeError,
    decode_project_manifest_bytes,
)

_MANIFEST_PATH = "project.manifest.json"
_PACKAGE = re.compile(r"[a-z][a-z0-9_]*")
_DEPENDENCY_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_PROBE_TIMEOUT_S = 30
_PROBE_SCRIPT = r'''
from noetrium import api
from __PACKAGE__.research import PORTFOLIO, PROGRAMS

if not isinstance(PORTFOLIO, api.ResearchPortfolio):
    raise TypeError("research module must export ResearchPortfolio")
if PORTFOLIO.portfolio_id != __PROJECT_ID__:
    raise ValueError("research portfolio identity must match the project identity")
if type(PROGRAMS) is not tuple or PROGRAMS != PORTFOLIO.programs:
    raise ValueError("research module PROGRAMS must equal portfolio programs")
if any(not isinstance(getattr(program, "program_id", None), str) for program in PROGRAMS):
    raise TypeError("research module PROGRAMS must contain Research Program values")
print("ready")
'''


def _check(
    check_id: str,
    ok: bool,
    summary: str,
    remediation: str,
) -> ProjectDoctorCheck:
    return ProjectDoctorCheck(
        check_id,
        ProjectDoctorDisposition.PASS if ok else ProjectDoctorDisposition.BLOCKED,
        summary,
        "" if ok else remediation,
    )


def _project_metadata(root: Path) -> tuple[str, str, tuple[str, ...]]:
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml is missing [project]")
    project_id = str(project.get("name", "")).strip()
    version = str(project.get("version", "")).strip()
    dependencies = project.get("dependencies", ())
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in dependencies
    ):
        raise ValueError("project dependencies must be a non-empty string array")
    return project_id, version, tuple(item.strip() for item in dependencies)


def _dependency_name(requirement: str) -> str:
    match = _DEPENDENCY_NAME.match(requirement)
    if match is None:
        raise ValueError("invalid project dependency requirement")
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def _pins_current_platform(
    dependencies: tuple[str, ...],
    platform_version: str,
) -> bool:
    try:
        platform_rows = tuple(
            item
            for item in dependencies
            if _dependency_name(item) == "noetrium"
        )
    except ValueError:
        return False
    expected = f"noetrium=={platform_version}".lower()
    return (
        len(platform_rows) == 1
        and re.sub(r"\s+", "", platform_rows[0]).lower() == expected
    )


def _manifest(root: Path) -> ProjectManifest | None:
    path = root / _MANIFEST_PATH
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return decode_project_manifest_bytes(path.read_bytes())
    except (OSError, ProjectManifestDecodeError):
        return None


def _compile_readiness(
    root: Path,
    package: str,
    project_id: str,
    *,
    command_runner: LocalCommandRunnerPort,
) -> tuple[bool, str]:
    if not _PACKAGE.fullmatch(package):
        return False, "invalid project package identity"
    command = isolated_script_command(
        _PROBE_SCRIPT
        .replace("__PACKAGE__", package)
        .replace("__PROJECT_ID__", repr(project_id)),
        project_src=root / "src",
    )
    try:
        completed = command_runner.run(
            command,
            cwd=root,
            environment=isolated_environment(),
            timeout_seconds=_PROBE_TIMEOUT_S,
        )
    except (LocalCommandStartError, LocalCommandTimeoutError):
        return False, "project compile probe could not complete"
    if completed.returncode != 0 or completed.stdout.strip() != "ready":
        return False, "project compile public contract probe failed closed"
    return True, "ready"


def doctor_project(
    project_root: Path,
    *,
    boundary_auditor: RepositoryBoundaryAuditor,
    command_runner: LocalCommandRunnerPort,
) -> ProjectDoctorReport:
    root = project_root.expanduser().absolute()
    checks: list[ProjectDoctorCheck] = []

    marker = root / ".noetrium-template"
    marker_value = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    expected_revision = project_template_revision()
    checks.append(_check(
        "template_revision",
        marker_value == expected_revision,
        "project template revision is current",
        "regenerate the project with the current unified template",
    ))

    try:
        project_id, project_version, dependencies = _project_metadata(root)
        metadata_ok = bool(project_id and project_version)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        project_id, project_version, dependencies, metadata_ok = "", "", (), False
    checks.append(_check(
        "project_metadata",
        metadata_ok,
        "pyproject project identity is readable",
        "restore the generated pyproject.toml project name/version",
    ))

    manifest = _manifest(root)
    checks.append(_check(
        "project_manifest",
        manifest is not None,
        "canonical digest-bound project manifest decodes successfully",
        "restore project.manifest.json from the canonical Portfolio codec",
    ))
    checks.append(_check(
        "manifest_template_revision",
        bool(manifest is not None and manifest.template_revision == expected_revision),
        "manifest template revision matches the unified template",
        "regenerate the project instead of editing template identity bytes",
    ))
    checks.append(_check(
        "manifest_identity",
        bool(
            manifest is not None
            and metadata_ok
            and manifest.project.identity.project_id == project_id
            and manifest.project.identity.version == project_version
        ),
        "manifest identity matches pyproject identity",
        "regenerate the project; do not hand-edit manifest identity bytes",
    ))

    platform = installed_platform_identity()
    checks.append(_check(
        "platform_version",
        _pins_current_platform(dependencies, platform.version),
        (
            f"project pins installed noetrium {platform.version}; "
            "additional project dependencies are allowed"
        ),
        (
            f"pin exactly noetrium=={platform.version}; "
            "declare additional Python dependencies normally in pyproject.toml"
        ),
    ))
    checks.append(_check(
        "platform_provenance",
        bool(
            manifest is not None
            and manifest.provenance.tool_version == platform.version
            and manifest.provenance.platform_artifact_sha256 == platform.artifact_sha256
        ),
        "manifest provenance matches the installed Platform artifact",
        "regenerate with the currently installed qualified Platform artifact",
    ))

    try:
        package = project_package_name(project_id) if project_id else ""
    except ValueError:
        package = ""
    required_files = () if not package else (
        _MANIFEST_PATH,
        f"src/{package}/core.py",
        f"src/{package}/research.py",
        "tests/test_generated_project.py",
    )
    files_ok = bool(required_files) and all(
        (root / relative).is_file() and not (root / relative).is_symlink()
        for relative in required_files
    )
    checks.append(_check(
        "generated_files",
        files_ok,
        "generated files match the unified project template",
        "restore or regenerate the deterministic project scaffold",
    ))

    generated_shell_ok = False
    generated_shell_detail = "generated Research OS shell is incomplete"
    if files_ok:
        try:
            expected_research = render_research_module(project_id).encode("utf-8")
            expected_test = render_generated_test_module(
                package,
                project_id,
            ).encode("utf-8")
            generated_shell_ok = (
                (root / f"src/{package}/research.py").read_bytes()
                == expected_research
                and (root / "tests/test_generated_project.py").read_bytes()
                == expected_test
            )
            generated_shell_detail = (
                "platform-owned Research OS shell/test projection drifted"
            )
        except (OSError, TypeError, ValueError, UnicodeError):
            generated_shell_ok = False
            generated_shell_detail = "generated Research OS shell cannot be validated"
    checks.append(_check(
        "generated_shell",
        generated_shell_ok,
        "platform-owned shell is deterministic and core remains user-owned",
        generated_shell_detail,
    ))

    try:
        boundary_report = boundary_auditor(root)
        boundary_ok = boundary_report.passed
        violation_detail = "; ".join(
            f"{row.path}: {row.detail}" for row in boundary_report.violations
        )
    except (OSError, ValueError):
        boundary_ok, violation_detail = False, "downstream import audit could not complete"
    checks.append(_check(
        "public_import_boundary",
        boundary_ok,
        "downstream source imports only the unified public API",
        violation_detail or "replace private Platform imports with noetrium.api",
    ))

    if files_ok:
        compile_ready, compile_detail = _compile_readiness(
            root,
            package,
            project_id,
            command_runner=command_runner,
        )
    else:
        compile_ready, compile_detail = False, "unified project files are incomplete"
    checks.append(_check(
        "standard_bindings",
        compile_ready,
        "user Program is valid and the generated shell lifts it into internal ResearchPortfolio IR",
        "resolve project compile readiness: " + compile_detail,
    ))

    return ProjectDoctorReport(
        project_root=str(root),
        template_revision=marker_value,
        checks=tuple(checks),
    )


__all__ = ["doctor_project"]