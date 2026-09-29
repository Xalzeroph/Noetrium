from __future__ import annotations

import json
from pathlib import Path

from scripts.release_distribution import _project_platform_source

from noetrium_platform.foundation.governance.architecture.repository_boundary.api import DownstreamImportKind
from noetrium_platform.foundation.governance.architecture.repository_boundary.runtime import (
    audit_downstream_project_imports,
    audit_repository_boundary,
)


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "noetrium_platform" / "foundation" / "governance" / "system_registry").mkdir(parents=True)
    (root / "noetrium_platform" / "core").mkdir(parents=True)
    (root / "deploy").mkdir()
    (root / "noetrium_platform" / "core" / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json").write_text(
        json.dumps({"governance": {"package_prefix": "noetrium_platform.foundation.governance"}}), encoding="utf-8"
    )
    (root / "pyproject.toml").write_text('[tool.setuptools.packages.find]\ninclude = ["noetrium_platform*"]\n', encoding="utf-8")
    (root / "deploy" / "Dockerfile").write_text("COPY noetrium_platform ./noetrium_platform\n", encoding="utf-8")
    return root


def test_clean_upstream_repository_passes(tmp_path: Path) -> None:
    report = audit_repository_boundary(_minimal_root(tmp_path))
    assert report.passed
    assert report.violations == ()


def test_downstream_directory_and_core_import_fail_closed(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "noetrium_platform" / "core" / "bad.py").write_text("from projects.demo import app\n", encoding="utf-8")
    report = audit_repository_boundary(root)
    codes = {row.code for row in report.violations}
    assert "DOWNSTREAM_PATH_IN_UPSTREAM" in codes
    assert "CORE_IMPORTS_DOWNSTREAM" in codes


def test_core_cannot_import_research_workspace(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    (root / "noetrium_platform" / "core" / "bad_research.py").write_text(
        "from research.reproductions.demo import method\n", encoding="utf-8"
    )
    (root / "noetrium" / "api").mkdir(parents=True)
    (root / "noetrium" / "api" / "bad_benchmark.py").write_text(
        "import benchmarks.private_cut\n", encoding="utf-8"
    )
    report = audit_repository_boundary(root)
    violations = [row for row in report.violations if row.code == "CORE_IMPORTS_RESEARCH_WORKSPACE"]
    assert len(violations) == 2
    assert {row.path for row in violations} == {
        "noetrium_platform/core/bad_research.py",
        "noetrium/api/bad_benchmark.py",
    }


def test_platform_source_projection_physically_removes_paper_workspace(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / "research" / "reproductions" / "paper").mkdir(parents=True)
    (root / "research" / "reproductions" / "paper" / "program.py").write_text("X = 1\n")
    (root / "benchmarks" / "paper").mkdir(parents=True)
    (root / "benchmarks" / "paper" / "cut.py").write_text("X = 1\n")
    (root / "docs" / "research").mkdir(parents=True)
    (root / "docs" / "research" / "paper.md").write_text("paper\n")
    (root / "noetrium_platform" / "research").mkdir(parents=True)
    (root / "noetrium_platform" / "research" / "__init__.py").write_text("PLATFORM = True\n")
    (root / "noetrium" ).mkdir(parents=True)
    (root / "noetrium" / "__init__.py").write_text("CORE = True\n")

    receipt = _project_platform_source(root)

    assert receipt["workspace_material_physically_removed"] is True
    assert receipt["removed_file_count"] == 3
    assert not (root / "research").exists()
    assert not (root / "benchmarks").exists()
    assert not (root / "docs" / "research").exists()
    assert (root / "noetrium_platform" / "research" / "__init__.py").is_file()
    assert (root / "noetrium" / "__init__.py").is_file()


def test_packaging_and_image_cannot_embed_downstream(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    (root / "pyproject.toml").write_text(
        'include = ["noetrium_platform*", "projects*", "research*"]\n', encoding="utf-8"
    )
    (root / "deploy" / "Dockerfile").write_text(
        "COPY projects ./projects\nCOPY research ./research\n", encoding="utf-8"
    )
    codes = {row.code for row in audit_repository_boundary(root).violations}
    assert "PACKAGE_INCLUDES_DOWNSTREAM" in codes
    assert "PACKAGE_INCLUDES_RESEARCH_WORKSPACE" in codes
    assert "IMAGE_COPIES_DOWNSTREAM" in codes
    assert "IMAGE_COPIES_RESEARCH_WORKSPACE" in codes


def test_release_manifest_cannot_publish_downstream_paths(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    (root / "RELEASE_MANIFEST.json").write_text(
        json.dumps({"files": [{"path": "research/reproductions/demo/program.py"}]}), encoding="utf-8"
    )
    report = audit_repository_boundary(root)
    assert any(row.code == "RELEASE_INCLUDES_DOWNSTREAM" for row in report.violations)


def test_bundled_minecraft_environment_is_upstream_owned(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    (root / "noetrium_platform" / "capabilities" / "environment" / "minecraft").mkdir(parents=True)
    catalog = root / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json"
    catalog.write_text(json.dumps({"environment/minecraft": {"package_prefix": "noetrium_platform.capabilities.environment.minecraft"}}), encoding="utf-8")
    (root / "RELEASE_MANIFEST.json").write_text(
        json.dumps({"files": [{"path": "noetrium_platform/capabilities/environment/minecraft/api/contracts.py"}]}), encoding="utf-8"
    )
    report = audit_repository_boundary(root)
    assert report.passed, report.violations


def test_unapproved_environment_provider_fails_closed(tmp_path: Path) -> None:
    root = _minimal_root(tmp_path)
    (root / "noetrium_platform" / "capabilities" / "environment" / "demo_world").mkdir(parents=True)
    catalog = root / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json"
    catalog.write_text(json.dumps({"environment/demo_world": {"package_prefix": "noetrium_platform.capabilities.environment.demo_world"}}), encoding="utf-8")
    codes = {row.code for row in audit_repository_boundary(root).violations}
    assert "CONCRETE_ENVIRONMENT_IN_UPSTREAM" in codes
    assert "REGISTRY_OWNS_DOWNSTREAM_ENVIRONMENT" in codes


def test_current_repository_boundary_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    report = audit_repository_boundary(root, include_release_manifest=False)
    assert report.passed, report.violations

def test_minimal_downstream_project_uses_one_noetrium_api(tmp_path: Path) -> None:
    root = tmp_path / "downstream"
    package = root / "src" / "example_project"
    package.mkdir(parents=True)
    (package / "app.py").write_text(
        "from noetrium.api import research_os\n",
        encoding="utf-8",
    )
    (package / "provider.py").write_text(
        "from noetrium import api\n"
        "ResearchPortfolioBuilder = api.ResearchPortfolioBuilder\n",
        encoding="utf-8",
    )
    report = audit_downstream_project_imports(root)
    assert report.passed, report.violations
    observed = {(row.module, row.kind) for row in report.observations}
    assert ("noetrium.api", DownstreamImportKind.NOETRIUM_API) in observed
    assert ("noetrium", DownstreamImportKind.NOETRIUM_API) in observed
    assert not (root / "noetrium_platform").exists()


def test_downstream_project_import_audit_ignores_platform_owned_state(tmp_path: Path) -> None:
    root = tmp_path / "downstream"
    package = root / "src" / "example_project"
    package.mkdir(parents=True)
    (package / "app.py").write_text(
        "from noetrium import api\n",
        encoding="utf-8",
    )
    state = root / ".noetrium" / "tmp"
    state.mkdir(parents=True)
    (state / "probe.py").write_text(
        "from noetrium_platform.foundation.kernel.kernel import Machine\n",
        encoding="utf-8",
    )

    report = audit_downstream_project_imports(root)

    assert report.passed, report.violations
    assert all(not row.path.startswith(".noetrium/") for row in report.observations)


def test_downstream_project_private_platform_import_and_vendoring_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "downstream"
    package = root / "src" / "example_project"
    package.mkdir(parents=True)
    (package / "bad.py").write_text(
        "from noetrium_platform.infrastructure.lifecycle.process.runtime import ProcessRuntime\n",
        encoding="utf-8",
    )
    (root / "noetrium_platform").mkdir()
    report = audit_downstream_project_imports(root)
    codes = {row.code for row in report.violations}
    assert "DOWNSTREAM_NON_UNIFIED_NOETRIUM_IMPORT" in codes
    assert "DOWNSTREAM_VENDORS_PLATFORM" in codes
    private = next(row for row in report.observations if row.module.startswith("noetrium_platform.infrastructure.lifecycle"))
    assert private.kind is DownstreamImportKind.FORBIDDEN_INTERNAL


def test_downstream_project_rejects_retired_noetrium_entrypoints(tmp_path: Path) -> None:
    root = tmp_path / "downstream"
    package = root / "src" / "example_project"
    package.mkdir(parents=True)
    (package / "bad.py").write_text(
        "from noetrium.contracts.discovery import load_downstream_capability_catalog\n"
        "from components.api import VersionedMemoryGraph\n"
        "from orchestration.api import MultiAgentRuntime\n",
        encoding="utf-8",
    )
    report = audit_downstream_project_imports(root)
    assert not report.passed
    assert {
        row.module
        for row in report.observations
        if row.kind is DownstreamImportKind.FORBIDDEN_INTERNAL
    } == {
        "noetrium.contracts.discovery",
        "components.api",
        "orchestration.api",
    }


def test_downstream_project_source_parse_failure_is_blocking(tmp_path: Path) -> None:
    root = tmp_path / "downstream"
    root.mkdir()
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    report = audit_downstream_project_imports(root)
    assert not report.passed
    assert {row.code for row in report.violations} == {"DOWNSTREAM_SOURCE_PARSE_FAILED"}
