from __future__ import annotations

from pathlib import Path

from scripts.server_common import _server_platform_meta_root


def test_server_platform_meta_root_is_one_durable_deterministic_identity(tmp_path: Path) -> None:
    env = {"NOETRIUM_DEPLOYMENT_STATE_ROOT": str(tmp_path / "state")}
    first = _server_platform_meta_root("node-a", env)
    second = _server_platform_meta_root("node-a", env)
    other = _server_platform_meta_root("node-b", env)

    assert first == second
    assert first != other
    assert first.parent == (tmp_path / "state" / "server-management").absolute()
    assert len(first.name) == 24
