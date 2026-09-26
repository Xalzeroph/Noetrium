from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from noetrium_platform.composition.operator.project import (
    project_doctor,
    project_scaffold,
    project_testing,
)
from noetrium_platform.composition.operator.project.project_platform_identity import (
    InstalledPlatformIdentity,
)
from noetrium_platform.foundation.governance.architecture.repository_boundary.runtime import (
    audit_downstream_project_imports,
)
from noetrium_platform.product.operator.api import ProjectCreateRequest
from noetrium_platform.foundation.portfolio.api import (
    decode_project_manifest_bytes,
    encode_project_manifest,
    project_manifest_identity_facets,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult
from noetrium_platform.product.operator.runtime.research_cli import (
    build_research_parser,
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


def test_create_emits_user_core_and_platform_owned_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    receipt = project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )

    generated = set(receipt.generated_files)
    assert "src/paper/core.py" in generated
    assert "src/paper/research.py" in generated
    assert "tests/test_generated_project.py" in generated
    assert "research.blueprint.json" not in generated
    assert "src/paper/slots.py" not in generated

    core = (root / "src" / "paper" / "core.py").read_text(encoding="utf-8")
    shell = (root / "src" / "paper" / "research.py").read_text(encoding="utf-8")
    assert "USER-OWNED scientific semantics" in core
    assert "build_research" in core
    assert "AUTO-GENERATED Research OS shell" in shell


def test_project_sync_never_parses_or_rewrites_user_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )

    core_path = root / "src" / "paper" / "core.py"
    custom = '''"""arbitrary user semantics"""
from noetrium import api


def build_research() -> api.ResearchPortfolio:
    a = api.ResearchProgramBuilder("paper-a")
    a.node("alpha", kind=api.ResearchNodeKind.CUSTOM)
    b = api.ResearchProgramBuilder("paper-b")
    b.node("beta", kind=api.ResearchNodeKind.CUSTOM)
    return api.ResearchPortfolio("paper", (a.freeze(), b.freeze()))


__all__ = ["build_research"]
'''
    core_path.write_text(custom, encoding="utf-8")
    before = core_path.read_bytes()

    shell_path = root / "src" / "paper" / "research.py"
    shell_path.write_text("drifted\n", encoding="utf-8")
    receipt = project_scaffold.sync_project(root)

    assert core_path.read_bytes() == before
    assert receipt.regenerated_files == (
        "src/paper/research.py",
        "tests/test_generated_project.py",
    )

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
        command_runner=_COMMAND_RUNNER,
    )
    checks = {row.check_id: row.disposition.value for row in report.checks}
    assert report.ready
    assert checks["generated_shell"] == "pass"
    assert checks["standard_bindings"] == "pass"
    assert project_testing.test_project(root, command_runner=_COMMAND_RUNNER).passed


def test_project_sync_rebinds_platform_provenance_without_scientific_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )

    manifest_path = root / "project.manifest.json"
    original = decode_project_manifest_bytes(manifest_path.read_bytes())
    enriched = replace(original, study_ids=("study-a",))
    manifest_path.write_bytes(encode_project_manifest(enriched))
    before_facets = project_manifest_identity_facets(enriched)

    rebound_platform = InstalledPlatformIdentity("0.1.0", "b" * 64)
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: rebound_platform,
    )
    monkeypatch.setattr(
        project_doctor,
        "installed_platform_identity",
        lambda: rebound_platform,
    )

    receipt = project_scaffold.sync_project(root)
    assert receipt.regenerated_files == (
        "project.manifest.json",
        "src/paper/research.py",
        "tests/test_generated_project.py",
    )

    rebound = decode_project_manifest_bytes(manifest_path.read_bytes())
    assert rebound.project == enriched.project
    assert rebound.capability_requirements == enriched.capability_requirements
    assert rebound.provider_bindings == enriched.provider_bindings
    assert rebound.method_requirements == enriched.method_requirements
    assert rebound.configuration_refs == enriched.configuration_refs
    assert rebound.study_ids == ("study-a",)
    assert rebound.provenance.platform_artifact_sha256 == "b" * 64

    after_facets = project_manifest_identity_facets(rebound)
    assert before_facets.project_spec_digest == after_facets.project_spec_digest
    assert before_facets.requirements_digest == after_facets.requirements_digest
    assert before_facets.provider_bindings_digest == after_facets.provider_bindings_digest
    assert (
        before_facets.scaffold_platform_provenance_digest
        != after_facets.scaffold_platform_provenance_digest
    )

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
        command_runner=_COMMAND_RUNNER,
    )
    assert report.ready


def test_doctor_rejects_hand_edited_generated_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )
    shell = root / "src" / "paper" / "research.py"
    shell.write_text(
        shell.read_text(encoding="utf-8") + "\n# hand edited\n",
        encoding="utf-8",
    )

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
        command_runner=_COMMAND_RUNNER,
    )
    checks = {row.check_id: row.disposition.value for row in report.checks}
    assert not report.ready
    assert checks["generated_shell"] == "blocked"


def test_project_cli_has_one_create_shape_and_sync() -> None:
    parser = build_research_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "project",
                "create",
                "paper",
                "out",
                "--blueprint",
                "paper.blueprint.json",
            ]
        )

    create = parser.parse_args(["project", "create", "paper", "out"])
    assert create.project_id == "paper"
    assert not hasattr(create, "blueprint")

    sync = parser.parse_args(["project", "sync", "--project", "out"])
    assert sync.project_root == Path("out")



def test_user_core_may_delegate_to_arbitrary_project_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "modular-paper"
    project_scaffold.create_project(
        ProjectCreateRequest("modular-paper", "0.1.0", root)
    )

    package_root = root / "src" / "modular_paper"
    (package_root / "semantics.py").write_text(
        '''from noetrium import api


def make_portfolio() -> api.ResearchPortfolio:
    first = api.ResearchProgramBuilder("paper-a")
    first.node("discover", kind=api.ResearchNodeKind.CUSTOM)
    second = api.ResearchProgramBuilder("paper-b")
    second.node("verify", kind=api.ResearchNodeKind.CUSTOM)
    portfolio = api.ResearchPortfolioBuilder("modular-paper")
    portfolio.program(first.freeze())
    portfolio.program(second.freeze())
    return portfolio.freeze()
''',
        encoding="utf-8",
    )
    (package_root / "core.py").write_text(
        '''from noetrium import api
from .semantics import make_portfolio


def build_research() -> api.ResearchPortfolio:
    return make_portfolio()


__all__ = ["build_research"]
''',
        encoding="utf-8",
    )

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
        command_runner=_COMMAND_RUNNER,
    )
    checks = {row.check_id: row.disposition.value for row in report.checks}
    assert report.ready
    assert checks["public_import_boundary"] == "pass"
    assert checks["standard_bindings"] == "pass"
    assert project_testing.test_project(
        root,
        command_runner=_COMMAND_RUNNER,
    ).passed



def test_generated_shell_is_independent_of_scientific_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "topology-independent"
    project_scaffold.create_project(
        ProjectCreateRequest("topology-independent", "0.1.0", root)
    )
    shell_path = root / "src" / "topology_independent" / "research.py"
    original_shell = shell_path.read_bytes()

    core_path = root / "src" / "topology_independent" / "core.py"
    core_path.write_text(
        '''from noetrium import api


def build_research() -> api.ResearchPortfolio:
    programs = []
    for program_id, node_ids in (
        ("paper-a", ("a0", "a1", "a2")),
        ("paper-b", ("b0", "b1")),
        ("paper-c", ("c0",)),
    ):
        builder = api.ResearchProgramBuilder(program_id)
        previous = None
        for node_id in node_ids:
            builder.node(node_id, kind=api.ResearchNodeKind.CUSTOM)
            if previous is not None:
                builder.depends(node_id, previous)
            previous = node_id
        programs.append(builder.freeze())
    return api.ResearchPortfolio("topology-independent", tuple(programs))


__all__ = ["build_research"]
''',
        encoding="utf-8",
    )

    project_scaffold.sync_project(root)

    assert shell_path.read_bytes() == original_shell
    assert project_testing.test_project(
        root,
        command_runner=_COMMAND_RUNNER,
    ).passed
