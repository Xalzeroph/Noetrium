from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition import runtime_coordination as coordination


def test_runtime_fabric_root_ignores_session_home_and_xdg(monkeypatch) -> None:
    canonical_home = coordination._canonical_user_home()
    monkeypatch.delenv("NOETRIUM_RUNTIME_FABRIC_ROOT", raising=False)
    monkeypatch.setenv("HOME", "/tmp/session-specific-home")
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/session-specific-state")

    root = coordination.runtime_fabric_root()

    expected_base = (
        canonical_home / ".local" / "state" / "noetrium" / "runtime-fabric"
    )
    assert root.is_relative_to(expected_base)
    assert "/tmp/session-specific" not in str(root)


def test_runtime_fabric_explicit_authority_overrides_canonical_home(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "fabric"
    monkeypatch.setenv("NOETRIUM_RUNTIME_FABRIC_ROOT", str(root))
    monkeypatch.setenv("HOME", "/tmp/ignored-home")

    resolved = coordination.runtime_fabric_root()

    assert resolved.is_relative_to(root)


def test_runtime_fabric_persistence_epoch_scopes_state_only(tmp_path: Path) -> None:
    from noetrium_platform.composition.managed_research_runtime import (
        _persistence_scoped_layout,
    )
    from noetrium_platform.foundation.kernel.unit_codec import UNIT_DOCUMENT_SCHEMA
    from noetrium_platform.infrastructure.resources.directory.runtime import (
        standard_local_directory_layout,
    )

    base = standard_local_directory_layout(tmp_path / "runtime")
    scoped = _persistence_scoped_layout(base)

    assert scoped.state == base.state / UNIT_DOCUMENT_SCHEMA
    assert scoped.cache == base.cache
    assert scoped.runtime == base.runtime
    assert scoped.model_artifacts == base.model_artifacts
    assert scoped.python_environments == base.python_environments
    assert scoped.logs == base.logs
    assert scoped.locks == base.locks
