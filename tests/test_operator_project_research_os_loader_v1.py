from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.operator.project import project_scaffold
from noetrium_platform.composition.operator.project.project_platform_identity import (
    InstalledPlatformIdentity,
)
from noetrium_platform.composition.operator.project import project_research_os_loader
from noetrium_platform.composition.operator.project.project_research_os_loader import (
    load_project_research_os,
)
from noetrium_platform.product.operator.api import ProjectCreateRequest
from noetrium_platform.product.research_os import ResearchExecutionTarget


_FIXED_PLATFORM = InstalledPlatformIdentity("0.1.0", "a" * 64)


def _create(root: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )


def test_generated_project_runs_directly_through_canonical_research_os(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    assert not (root / "src" / "paper" / "application.py").exists()

    loaded = load_project_research_os(root)
    try:
        assert loaded.portfolio.portfolio_id == "paper"
        assert loaded.revision.portfolio_digest == loaded.portfolio.portfolio_digest
        assert loaded.execution_plane_ready is False
        target = ResearchExecutionTarget(
            loaded.default_execution_id,
            loaded.revision,
        )
        ran = loaded.research_os.run(target)
        assert loaded.execution_plane_ready is True
        assert ran.state == "succeeded"

        inspected = loaded.research_os.inspect(target)
        assert inspected.payload["states"]["succeeded"] == ("paper::root",)
    finally:
        loaded.close()


def test_project_source_edit_auto_parents_active_revision_without_runtime_glue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)

    first = load_project_research_os(root)
    try:
        target = ResearchExecutionTarget(
            first.default_execution_id,
            first.revision,
        )
        assert first.research_os.run(target).state == "succeeded"
        first_revision = first.revision
    finally:
        first.close()

    core = root / "src" / "paper" / "core.py"
    core.write_text(
        '''from noetrium import api


def changed():
    return None


def build_research() -> api.ResearchPortfolio:
    portfolio = api.ResearchPortfolioBuilder("paper")
    program = portfolio.program("paper")
    program.custom_definition("changed", implementation=changed)
    program.custom_node("root", definitions=("changed",))
    return portfolio.freeze()


__all__ = ["build_research"]
''',
        encoding="utf-8",
    )

    second = load_project_research_os(root)
    try:
        assert second.revision != first_revision
        assert second.revision.parent_revision_digests == (
            first_revision.revision_digest,
        )
        assert second.revision.portfolio_digest == second.portfolio.portfolio_digest
        assert not (root / "src" / "paper" / "application.py").exists()
    finally:
        second.close()


def test_project_open_is_control_plane_only(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)

    def forbidden_runtime(*args, **kwargs):
        raise AssertionError("project open must not materialize physical runtime")

    monkeypatch.setattr(
        project_research_os_loader,
        "build_local_managed_research_runtime",
        forbidden_runtime,
    )
    loaded = load_project_research_os(root)
    try:
        assert loaded.execution_plane_ready is False
        assert loaded.portfolio.portfolio_id == "paper"
    finally:
        loaded.close()
