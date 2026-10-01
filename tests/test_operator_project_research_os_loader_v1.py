from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.managed_research_runtime import ManagedResearchRuntime
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
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
)


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


def _stub_background_controllers(monkeypatch):
    started = []

    def start(runtime, *args, **kwargs):
        started.append(runtime)

    monkeypatch.setattr(ManagedResearchRuntime, "start_background_controllers", start)
    return started


def test_generated_project_runs_directly_through_canonical_research_os(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    started = _stub_background_controllers(monkeypatch)
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
        assert started == [loaded._managed_runtime]
        assert loaded._managed_runtime is not None
        assert loaded._managed_runtime._fabric_consumer_lease is not None
        assert (
            loaded._managed_runtime._fabric_consumer_lease.holder_scope
            == loaded.manifest.project.identity.scope
        )
        assert ran.state == "succeeded"

        inspected = loaded.research_os.inspect(target)
        assert inspected.payload["states"]["succeeded"] == ("paper::root",)
    finally:
        loaded.close()


def test_live_fleet_hot_detach_and_rejoin_preserves_other_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    monkeypatch.setenv(
        "NOETRIUM_RUNTIME_FABRIC_ROOT",
        str(tmp_path / "runtime-fabric"),
    )
    _stub_background_controllers(monkeypatch)

    root_a = tmp_path / "paper-a"
    root_b = tmp_path / "paper-b"
    project_scaffold.create_project(ProjectCreateRequest("paper-a", "0.1.0", root_a))
    project_scaffold.create_project(ProjectCreateRequest("paper-b", "0.1.0", root_b))

    a = load_project_research_os(root_a)
    b = load_project_research_os(root_b)
    b2 = None
    try:
        target_a = ResearchExecutionTarget(a.default_execution_id, a.revision)
        target_b = ResearchExecutionTarget(b.default_execution_id, b.revision)
        ran_a = a.research_os.run(target_a)
        ran_b = b.research_os.run(target_b)
        assert ran_a.state == ran_b.state == "succeeded"
        cut_a = ran_a.payload["cut_id"]
        first_b_revision = b.revision

        resource = ResourceIdentity(ResourceKind.RUNTIME_FABRIC, "host-runtime-fabric")
        registry = a._managed_runtime.management.platform_meta.resource_leases
        active = registry.active_for(resource)
        assert {row.holder_scope for row in active} == {
            a.manifest.project.identity.scope,
            b.manifest.project.identity.scope,
        }

        # Hot-detach only B. A's durable cut and live Runtime Fabric membership
        # must survive unchanged.
        b.close()
        active = registry.active_for(resource)
        assert tuple(row.holder_scope for row in active) == (
            a.manifest.project.identity.scope,
        )
        assert a.research_os.inspect(target_a).payload["cut_id"] == cut_a

        # Edit B while A continues running, then attach the new immutable B
        # revision to the same live Runtime Fabric.
        core_b = root_b / "src" / "paper_b" / "core.py"
        core_b.write_text(
            core_b.read_text(encoding="utf-8") + "\n# hot-rejoin-revision\n",
            encoding="utf-8",
        )
        b2 = load_project_research_os(root_b)
        assert b2.revision != first_b_revision
        assert b2.revision.parent_revision_digests == (
            first_b_revision.revision_digest,
        )
        target_b2 = ResearchExecutionTarget(b2.default_execution_id, b2.revision)
        assert b2.research_os.run(target_b2).state == "succeeded"

        active = registry.active_for(resource)
        assert {row.holder_scope for row in active} == {
            a.manifest.project.identity.scope,
            b2.manifest.project.identity.scope,
        }
        assert a.research_os.inspect(target_a).payload["cut_id"] == cut_a
    finally:
        if b2 is not None:
            b2.close()
        elif not b._closed:
            b.close()
        a.close()


def test_project_source_edit_auto_parents_active_revision_without_runtime_glue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    started = _stub_background_controllers(monkeypatch)

    first = load_project_research_os(root)
    try:
        target = ResearchExecutionTarget(
            first.default_execution_id,
            first.revision,
        )
        assert first.research_os.run(target).state == "succeeded"
        assert started == [first._managed_runtime]
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
    program = portfolio.programs.create("paper")
    program.extensions.define("changed", implementation=changed)
    program.extensions.node("root", definitions=("changed",))
    return portfolio.freeze()


__all__ = ["build_research"]
''',
        encoding="utf-8",
    )

    second = load_project_research_os(root)
    try:
        assert second.revision != first_revision
        # Opening/recompiling a project remains control-plane only. The second
        # runtime is not materialized until an execution control reaches it.
        assert second._managed_runtime is None
        assert len(started) == 1
        assert second.revision.parent_revision_digests == (
            first_revision.revision_digest,
        )
        assert second.revision.portfolio_digest == second.portfolio.portfolio_digest
        assert not (root / "src" / "paper" / "application.py").exists()
    finally:
        second.close()


def test_running_revision_uses_immutable_source_snapshot_when_worktree_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    _stub_background_controllers(monkeypatch)

    loaded = load_project_research_os(root)
    try:
        snapshot_core = loaded._source_snapshot_src / "paper" / "core.py"
        snapshot_bytes = snapshot_core.read_bytes()
        live_core = root / "src" / "paper" / "core.py"
        live_text = live_core.read_text(encoding="utf-8")
        live_core.write_text(
            live_text.replace("return None", "return 7", 1),
            encoding="utf-8",
        )

        assert live_core.read_bytes() != snapshot_bytes
        assert snapshot_core.read_bytes() == snapshot_bytes
        assert loaded.revision.message.endswith(loaded.source_snapshot_digest)

        target = ResearchExecutionTarget(
            loaded.default_execution_id,
            loaded.revision,
        )
        assert loaded.research_os.run(target).state == "succeeded"
        assert snapshot_core.read_bytes() == snapshot_bytes
    finally:
        loaded.close()


def test_stopped_project_can_run_new_revision_without_touching_old_cut(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    _stub_background_controllers(monkeypatch)

    first = load_project_research_os(root)
    try:
        first_target = ResearchExecutionTarget(
            first.default_execution_id, first.revision
        )
        assert first.research_os.run(first_target).state == "succeeded"
        assert first.research_os.pause(first_target).state == "paused"
        first_revision = first.revision
        first_cut = first.research_os.inspect(first_target).payload["cut_id"]
    finally:
        first.close()

    core = root / "src" / "paper" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8").replace(
            "return None", "marker = 2\n    return None", 1
        ),
        encoding="utf-8",
    )

    second = load_project_research_os(root)
    try:
        assert second.revision != first_revision
        second_target = ResearchExecutionTarget(
            second.default_execution_id, second.revision
        )
        ran = second.research_os.run(second_target)
        assert ran.state == "succeeded"
        assert ran.payload["cut_id"] != first_cut
        assert second.active_revision == first_revision
        assert second.revision.parent_revision_digests == (
            first_revision.revision_digest,
        )
    finally:
        second.close()


def test_active_control_uses_immutable_snapshot_while_worktree_is_invalid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    _stub_background_controllers(monkeypatch)

    first = load_project_research_os(root)
    try:
        target = ResearchExecutionTarget(first.default_execution_id, first.revision)
        assert first.research_os.run(target).state == "succeeded"
        assert first.research_os.pause(target).state == "paused"
        frozen_revision = first.revision
        frozen_digest = first.source_snapshot_digest
    finally:
        first.close()

    # Simulate an operator editing the next revision while the old cut is still
    # the authoritative running/paused revision.  ACTIVE control must never
    # import or snapshot this temporarily invalid source tree.
    core = root / "src" / "paper" / "core.py"
    core.write_text("this is not valid python !!!\n", encoding="utf-8")

    active = load_project_research_os(root, revision_intent="active")
    try:
        assert active.revision == frozen_revision
        assert active.active_revision == frozen_revision
        assert active.source_snapshot_digest == frozen_digest
        target = ResearchExecutionTarget(active.default_execution_id, active.revision)
        assert active.research_os.inspect(target).state == "paused"
    finally:
        active.close()


def test_active_resume_uses_frozen_source_after_worktree_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    _stub_background_controllers(monkeypatch)

    first = load_project_research_os(root)
    try:
        target = ResearchExecutionTarget(first.default_execution_id, first.revision)
        assert first.research_os.run(target).state == "succeeded"
        assert first.research_os.pause(target).state == "paused"
        frozen_revision = first.revision
    finally:
        first.close()

    live_core = root / "src" / "paper" / "core.py"
    live_core.write_text("def broken(:\n", encoding="utf-8")

    active = load_project_research_os(root, revision_intent="active")
    try:
        assert active.revision == frozen_revision
        target = ResearchExecutionTarget(active.default_execution_id, active.revision)
        resumed = active.research_os.resume(target)
        assert resumed.state == "succeeded"
    finally:
        active.close()


def test_project_loader_rejects_unknown_revision_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    try:
        load_project_research_os(root, revision_intent="legacy")
    except ValueError as exc:
        assert "revision_intent" in str(exc)
    else:
        raise AssertionError("unknown project revision intent was accepted")


def test_dependency_only_source_edit_creates_new_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "paper"
    _create(root, monkeypatch)
    started = _stub_background_controllers(monkeypatch)

    helper = root / "src" / "paper" / "helper.py"
    helper.write_text("def value():\n    marker = 1\n    return None\n", encoding="utf-8")
    core = root / "src" / "paper" / "core.py"
    core_text = core.read_text(encoding="utf-8")
    core.write_text(
        core_text.replace(
            "from noetrium import api\n",
            "from noetrium import api\nfrom . import helper\n",
            1,
        ).replace(
            "    return None\n",
            "    return helper.value()\n",
            1,
        ),
        encoding="utf-8",
    )

    first = load_project_research_os(root)
    try:
        target = ResearchExecutionTarget(
            first.default_execution_id,
            first.revision,
        )
        assert first.research_os.run(target).state == "succeeded"
        assert started == [first._managed_runtime]
        first_revision = first.revision
        first_portfolio_digest = first.portfolio.portfolio_digest
        first_source_digest = first.source_snapshot_digest
    finally:
        first.close()

    helper.write_text("def value():\n    marker = 2\n    return None\n", encoding="utf-8")

    second = load_project_research_os(root)
    try:
        assert second.portfolio.portfolio_digest == first_portfolio_digest
        assert second.source_snapshot_digest != first_source_digest
        assert second.revision != first_revision
        assert second.revision.parent_revision_digests == (
            first_revision.revision_digest,
        )
        assert second.revision.message.endswith(second.source_snapshot_digest)
        assert second._managed_runtime is None
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



def test_project_non_execution_controls_are_control_plane_only() -> None:
    calls = []

    class Owner:
        def ensure_execution_plane(self):
            raise AssertionError(
                "durable stop-side control must not materialize physical runtime"
            )

    class Delegate:
        def pause(self, target, payload=None):
            calls.append(("pause", target, payload))
            return "paused"

        def drain(self, target, payload=None):
            calls.append(("drain", target, payload))
            return "draining"

        def interrupt(self, target, payload=None):
            calls.append(("interrupt", target, payload))
            return "interrupted"

        def cancel(self, target, payload=None):
            calls.append(("cancel", target, payload))
            return "cancelled"

    proxy = project_research_os_loader._LazyProjectResearchOS(Owner(), Delegate())
    assert proxy.pause("paper") == "paused"
    assert proxy.drain("paper") == "draining"
    assert proxy.interrupt("paper") == "interrupted"
    assert proxy.cancel("paper") == "cancelled"
    assert calls == [
        ("pause", "paper", None),
        ("drain", "paper", None),
        ("interrupt", "paper", None),
        ("cancel", "paper", None),
    ]


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


def test_project_open_failure_releases_immutable_source_retain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys
    import pytest

    root = tmp_path / "paper"
    _create(root, monkeypatch)

    def fail_composition(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("composition failed")

    monkeypatch.setattr(
        project_research_os_loader,
        "compose_local_research_os",
        fail_composition,
    )
    with pytest.raises(RuntimeError, match="composition failed"):
        load_project_research_os(root)

    package = project_research_os_loader.project_package_name("paper")
    assert package not in project_research_os_loader._ACTIVE_PROJECT_SOURCES
    assert not any(
        "source-snapshots" in entry and entry.endswith("/src")
        for entry in sys.path
    )


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
    _create(root, monkeypatch)
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
    loaded = load_project_research_os(root)
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
    _create(root, monkeypatch)

    class Shared:
        pass

    # The loader type-checks shared runtimes, so construct the loaded handle
    # normally and set only the internal ownership marker under test.
    loaded = load_project_research_os(root)
    loaded._shared_runtime = Shared()
    try:
        with pytest.raises(RuntimeError, match="shared ManagedResearchRuntime"):
            loaded.retire_runtime_fabric()
    finally:
        loaded._shared_runtime = None
        loaded.close()
