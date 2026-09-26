from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.operator.project import project_scaffold
from noetrium_platform.composition.operator.project.project_platform_identity import (
    InstalledPlatformIdentity,
)
from noetrium_platform.composition.operator.project.project_research_os_loader import (
    load_project_research_os,
)
from noetrium_platform.product.operator.api import ProjectCreateRequest


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
        target = api.research_os.ResearchExecutionTarget(
            loaded.default_execution_id,
            loaded.revision,
        )
        ran = loaded.research_os.run(target)
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
        target = api.research_os.ResearchExecutionTarget(
            first.default_execution_id,
            first.revision,
        )
        assert first.research_os.run(target).state == "succeeded"
        first_revision = first.revision
    finally:
        first.close()

    core = root / "src" / "paper" / "core.py"
    core.write_text(
        '''from noetrium.api import research_os as api


def changed():
    return None


def build_research() -> api.ResearchPortfolio:
    program = api.ResearchProgramBuilder("paper")
    program.definition(
        "changed",
        kind=api.ResearchDefinitionKind.CUSTOM,
        implementation=changed,
    )
    program.node(
        "root",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("changed",),
    )
    return api.ResearchPortfolio("paper", (program.freeze(),))


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
