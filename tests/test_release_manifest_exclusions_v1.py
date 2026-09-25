from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.release.runtime.manifest import _iter_release_files


def test_release_file_projection_excludes_controller_state_and_local_profiles(tmp_path: Path) -> None:
    (tmp_path / ".server-state" / "server-sessions").mkdir(parents=True)
    (tmp_path / ".server-state" / "server-sessions" / "operations.jsonl").write_text(
        "private controller evidence", encoding="utf-8"
    )
    (tmp_path / ".local" / "algorithm-governance").mkdir(parents=True)
    (tmp_path / ".local" / "algorithm-governance" / "ALGORITHM_CURRENT.json").write_text(
        "local advisory state", encoding="utf-8"
    )
    (tmp_path / "bridge" / "node_modules" / "vec3").mkdir(parents=True)
    (tmp_path / "bridge" / "node_modules" / "vec3" / "index.js").write_text(
        "generated dependency install", encoding="utf-8"
    )
    (tmp_path / "configs" / "server_profiles").mkdir(parents=True)
    (tmp_path / "configs" / "server_profiles" / "server-a.validation.local.env").write_text(
        "RP_SERVER_SERVER_A_HOST=private", encoding="utf-8"
    )
    (tmp_path / "configs" / "server_profiles" / "example.env").write_text(
        "RP_SERVER_CATALOG_IDS=server-a", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("public", encoding="utf-8")
    (tmp_path / "RELEASE_AUTHORITY.json").write_text("derived", encoding="utf-8")

    paths = {relative.as_posix() for _path, relative in _iter_release_files(tmp_path)}
    assert "README.md" in paths
    assert "configs/server_profiles/example.env" in paths
    assert ".server-state/server-sessions/operations.jsonl" not in paths
    assert ".local/algorithm-governance/ALGORITHM_CURRENT.json" not in paths
    assert "bridge/node_modules/vec3/index.js" not in paths
    assert "configs/server_profiles/server-a.validation.local.env" not in paths
    assert "RELEASE_AUTHORITY.json" not in paths
