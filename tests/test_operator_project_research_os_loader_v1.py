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


def _create(root: Path, monkeypatch) -> Path:
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )
    config = root / "test-execution.json"
    config.write_text(
        '{"schema":"noetrium.project-execution-config.v1","start_background_controllers":false}\n',
        encoding="utf-8",
    )
    return config


def test_generated_project_runs_directly_through_canonical_research_os(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    config = _create(root, monkeypatch)
    assert not (root / "src" / "paper" / "application.py").exists()

    loaded = load_project_research_os(root, config_path=config)
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
    config = _create(root, monkeypatch)

    first = load_project_research_os(root, config_path=config)
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

    second = load_project_research_os(root, config_path=config)
    try:
        assert second.revision != first_revision
        assert second.revision.parent_revision_digests == (
            first_revision.revision_digest,
        )
        assert second.revision.portfolio_digest == second.portfolio.portfolio_digest
        assert not (root / "src" / "paper" / "application.py").exists()
    finally:
        second.close()


def test_project_state_root_can_be_physically_externalized(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "paper"
    project.mkdir()
    external = tmp_path / "noetrium-data" / "projects" / "paper" / "research-os"
    monkeypatch.setenv("NOETRIUM_PROJECT_STATE_ROOT", str(external))
    resolved = project_research_os_loader._project_state_root(project)
    assert resolved == external
    assert external.is_dir()
    assert not (project / ".noetrium").exists()


def test_project_state_root_rejects_relative_externalization(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "paper"
    project.mkdir()
    monkeypatch.setenv("NOETRIUM_PROJECT_STATE_ROOT", "relative/state")
    try:
        project_research_os_loader._project_state_root(project)
    except ValueError as exc:
        assert "absolute path" in str(exc)
    else:
        raise AssertionError("relative project state root was accepted")



def test_project_reconcile_is_control_plane_only() -> None:
    calls = []

    class Owner:
        def ensure_execution_plane(self):
            raise AssertionError("reconcile must not materialize physical runtime")

    class Delegate:
        def reconcile(self, target, payload=None):
            calls.append((target, payload))
            return "reconciled"

    proxy = project_research_os_loader._LazyProjectResearchOS(Owner(), Delegate())
    assert proxy.reconcile("target", {"proof": "durable"}) == "reconciled"
    assert calls == [("target", {"proof": "durable"})]


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


def test_project_terminal_retirement_uses_managed_runtime_without_execution_authorities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    config = _create(root, monkeypatch)
    calls = []

    class Runtime:
        def retire_runtime_fabric(self):
            calls.append("retire")

        def close(self):
            calls.append("close")

    runtime = Runtime()

    def build_runtime(*args, **kwargs):
        calls.append(("build", args, kwargs))
        return runtime

    monkeypatch.setattr(
        project_research_os_loader,
        "build_local_managed_research_runtime",
        build_runtime,
    )
    loaded = load_project_research_os(root, config_path=config)
    try:
        assert loaded.execution_plane_ready is False
        assert loaded._execution_authorities is None
        loaded.retire_runtime_fabric()
        assert calls[0][0] == "build"
        assert calls[0][2]["start_background_controllers"] is False
        assert calls[1] == "retire"
        assert loaded._execution_authorities is None
    finally:
        loaded.close()
    assert calls[-1] == "close"


def test_project_terminal_retirement_refuses_shared_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pytest

    root = tmp_path / "paper"
    config = _create(root, monkeypatch)

    class Shared:
        pass

    # The loader type-checks shared runtimes, so construct the loaded handle
    # normally and set only the internal ownership marker under test.
    loaded = load_project_research_os(root, config_path=config)
    loaded._shared_runtime = Shared()
    try:
        with pytest.raises(RuntimeError, match="shared ManagedResearchRuntime"):
            loaded.retire_runtime_fabric()
    finally:
        loaded._shared_runtime = None
        loaded.close()
