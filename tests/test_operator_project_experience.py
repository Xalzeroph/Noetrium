from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from noetrium_platform.foundation.governance.repository_boundary.runtime import (
    audit_downstream_project_imports,
)
from noetrium_platform.foundation.portfolio.api import (
    decode_project_manifest_bytes,
    encode_project_manifest,
    project_manifest_document,
)
from noetrium_platform.product.operator.api import (
    PROJECT_TEMPLATE_REVISION,
    ProjectCreateRequest,
    ProjectDoctorDisposition,
    ProjectTestStage,
)
from noetrium_platform.product.operator.composition.research import main
from noetrium_platform.product.operator.runtime import (
    project_doctor,
    project_scaffold,
    project_testing,
)
from noetrium_platform.product.operator.runtime.project_platform_identity import (
    InstalledPlatformIdentity,
)
from noetrium_platform.product.operator.runtime.research_cli import build_research_parser

_FIXED_PLATFORM = InstalledPlatformIdentity("0.1.0", "a" * 64)


def _bind_fixed_platform(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _checks(report) -> dict[str, ProjectDoctorDisposition]:
    return {row.check_id: row.disposition for row in report.checks}


def test_project_create_uses_one_canonical_manifest_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "demo-project"
    request = ProjectCreateRequest("demo-project", "0.1.0", root)

    first = project_scaffold.create_project(request)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    second = project_scaffold.create_project(request)
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    manifest = decode_project_manifest_bytes((root / "project.manifest.json").read_bytes())
    assert manifest.project.identity.project_id == "demo-project"
    assert manifest.project.identity.version == "0.1.0"
    assert manifest.project.program_id == "demo-project"
    assert manifest.template_revision == PROJECT_TEMPLATE_REVISION
    assert manifest.provenance.platform_artifact_sha256 == "a" * 64
    assert first.template_revision == PROJECT_TEMPLATE_REVISION
    assert first.manifest_semantic_digest == project_manifest_document(manifest)["semantic_digest"]
    assert first == second
    assert before == after


def test_unified_scaffold_contains_only_scientific_authoring_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "unified"
    receipt = project_scaffold.create_project(
        ProjectCreateRequest("demo.project-alpha", "0.1.0", root)
    )
    generated = set(receipt.generated_files)
    assert "src/demo_project_alpha/method.py" in generated
    assert "src/demo_project_alpha/study.py" in generated
    assert "tests/test_generated_project.py" in generated
    for retired in (
        "project.py",
        "research.py",
        "requirements.py",
        "participant_provider.py",
        "model_provider.py",
        "environment_provider.py",
        "application.py",
    ):
        assert f"src/demo_project_alpha/{retired}" not in generated


def test_project_create_rejects_drift_and_unexpected_files_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "demo-project"
    request = ProjectCreateRequest("demo-project", "0.1.0", root)
    project_scaffold.create_project(request)
    readme = root / "README.md"
    readme.write_text("user change\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identical generated scaffold"):
        project_scaffold.create_project(request)
    assert readme.read_text(encoding="utf-8") == "user change\n"

    readme.write_text(
        project_scaffold._readme("demo-project"),  # exact generated content
        encoding="utf-8",
    )
    unexpected = root / "extra.txt"
    unexpected.write_text("not generated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected=.*extra.txt"):
        project_scaffold.create_project(request)
    assert unexpected.read_text(encoding="utf-8") == "not generated\n"


def test_project_create_cleans_partial_publication_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "demo-project"
    request = ProjectCreateRequest("demo-project", "0.1.0", root)
    original = project_scaffold.atomic_replace_bytes
    calls = 0

    def fail_publication(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication failure")
        original(path, payload)

    monkeypatch.setattr(project_scaffold, "atomic_replace_bytes", fail_publication)
    with pytest.raises(OSError, match="injected publication failure"):
        project_scaffold.create_project(request)
    assert not root.exists()


def test_project_doctor_validates_one_compile_surface_and_public_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "demo-project"
    project_scaffold.create_project(ProjectCreateRequest("demo-project", "0.1.0", root))

    report = project_doctor.doctor_project(
        root, boundary_auditor=audit_downstream_project_imports
    )
    checks = _checks(report)
    assert report.template_revision == PROJECT_TEMPLATE_REVISION
    assert report.ready
    assert checks["project_manifest"] is ProjectDoctorDisposition.PASS
    assert checks["manifest_identity"] is ProjectDoctorDisposition.PASS
    assert checks["public_import_boundary"] is ProjectDoctorDisposition.PASS
    assert checks["standard_bindings"] is ProjectDoctorDisposition.PASS
    assert not any("provider" in check_id for check_id in checks)

    private_source = root / "src" / "demo_project" / "private_import.py"
    private_source.write_text(
        "from noetrium_platform.product.operator.runtime import research_cli\n",
        encoding="utf-8",
    )
    drifted = project_doctor.doctor_project(
        root, boundary_auditor=audit_downstream_project_imports
    )
    assert _checks(drifted)["public_import_boundary"] is ProjectDoctorDisposition.BLOCKED


def test_project_doctor_rejects_unknown_manifest_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "demo-project"
    project_scaffold.create_project(ProjectCreateRequest("demo-project", "0.1.0", root))
    manifest_path = root / "project.manifest.json"
    manifest = decode_project_manifest_bytes(manifest_path.read_bytes())
    manifest_path.write_bytes(
        encode_project_manifest(
            replace(manifest, template_revision="noetrium.project-template.v999")
        )
    )
    report = project_doctor.doctor_project(
        root, boundary_auditor=audit_downstream_project_imports
    )
    checks = _checks(report)
    assert checks["project_manifest"] is ProjectDoctorDisposition.PASS
    assert checks["manifest_template_revision"] is ProjectDoctorDisposition.BLOCKED
    assert not report.ready


def test_project_test_runs_generated_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "demo-project"
    project_scaffold.create_project(ProjectCreateRequest("demo-project", "0.1.0", root))
    receipt = project_testing.test_project(root)
    assert receipt.passed
    assert tuple(stage.stage for stage in receipt.stages) == (
        ProjectTestStage.BUILD_INSTALL,
        ProjectTestStage.CONTRACT_TEST,
    )


def test_project_test_timeout_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "demo-project"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires=[]\nbuild-backend="missing"\n',
        encoding="utf-8",
    )

    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired(("python", "-m", "unittest"), 120)

    monkeypatch.setattr(project_testing.subprocess, "run", timeout)
    receipt = project_testing.test_project(root)
    assert len(receipt.stages) == 1
    assert receipt.stages[0].stage is ProjectTestStage.BUILD_INSTALL
    assert receipt.stages[0].exit_code == 124
    assert not receipt.passed


def test_project_cli_has_no_template_selector_and_emits_single_project_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _bind_fixed_platform(monkeypatch)
    parser = build_research_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "project", "create", "x", str(tmp_path / "x"),
            "--version", "0.1.0", "--template", "provider",
        ])

    with pytest.raises(SystemExit):
        parser.parse_args([
            "project", "create", "x", str(tmp_path / "program-x"),
            "--version", "0.1.0", "--program-id", "program",
        ])

    root = tmp_path / "demo-project"
    assert main([
        "project", "create", "demo-project", str(root),
        "--version", "0.1.0",
    ]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["ok"] is True
    assert created["result"]["template_revision"] == PROJECT_TEMPLATE_REVISION
    assert "template_profile" not in created["result"]

    assert main(["project", "doctor", "--project", str(root)]) == 0
    diagnosed = json.loads(capsys.readouterr().out)
    assert diagnosed["result"]["template_revision"] == PROJECT_TEMPLATE_REVISION
    assert "template_profile" not in diagnosed["result"]
    checks = {
        row["check_id"]: row["disposition"]
        for row in diagnosed["result"]["checks"]
    }
    assert checks["standard_bindings"] == "pass"


def test_runtime_application_is_optional_extension_of_same_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "project-route"
    project_scaffold.create_project(
        ProjectCreateRequest("project-route", "0.1.0", root)
    )

    assert main(["run", "--project", str(root)]) == 2
    missing = json.loads(capsys.readouterr().err)
    assert "no runtime application" in missing["error"].lower()

    application = root / "src" / "project_route" / "application.py"
    application.write_text(
        "from noetrium.api import ResearchResult\n\n"
        "class Application:\n"
        "    def execute(self, request):\n"
        "        return ResearchResult(request.action, request.target, 'accepted', {'route': 'project'})\n\n"
        "def build_application(config_path):\n"
        "    del config_path\n"
        "    return Application()\n",
        encoding="utf-8",
    )
    assert main(["run", "--project", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["target"] == "project-route"
    assert result["result"]["state"] == "accepted"
    assert result["result"]["payload"] == {"route": "project"}


def test_root_product_api_exports_project_test_stage_types() -> None:
    from noetrium.api import ProjectTestStageReceipt

    receipt = ProjectTestStageReceipt(ProjectTestStage.BUILD_INSTALL, ("python",), 0)
    assert receipt.passed
