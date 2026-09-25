from __future__ import annotations

from pathlib import Path

import pytest

import noetrium_platform.capabilities.environment.minecraft.providers.world_cut as world_cut


def _legacy_manifest(root: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if world_cut._excluded(relative):
            continue
        if path.is_symlink():
            raise AssertionError("test fixture must not contain symlinks")
        if path.is_file():
            rows.append(
                {
                    "path": relative.as_posix(),
                    "size": path.stat().st_size,
                    "sha256": world_cut._sha256(path),
                }
            )
    return tuple(rows)


def _fixture(root: Path) -> None:
    (root / "a" / "nested").mkdir(parents=True)
    (root / "research-world").mkdir()
    (root / "logs" / "deep").mkdir(parents=True)
    (root / "crash-reports").mkdir()
    (root / "a-z.txt").write_bytes(b"prefix-order")
    (root / "a" / "nested" / "item.bin").write_bytes(b"nested")
    (root / "research-world" / "level.dat").write_bytes(b"level")
    (root / "research-world" / "session.lock").write_bytes(b"volatile")
    (root / "logs" / "deep" / "ignored.log").write_bytes(b"ignored")
    (root / "crash-reports" / "ignored.txt").write_bytes(b"ignored")


def test_manifest_preserves_legacy_order_and_digest_semantics(tmp_path) -> None:
    root = tmp_path / "world"
    _fixture(root)

    assert world_cut._tree_manifest(root) == _legacy_manifest(root)


def test_manifest_prunes_excluded_directories_before_descending(tmp_path, monkeypatch) -> None:
    root = tmp_path / "world"
    _fixture(root)
    original_walk = world_cut.os.walk
    visited: list[str] = []

    def tracking_walk(*args, **kwargs):
        for current, directories, names in original_walk(*args, **kwargs):
            visited.append(Path(current).relative_to(root).as_posix())
            yield current, directories, names

    monkeypatch.setattr(world_cut.os, "walk", tracking_walk)
    manifest = world_cut._tree_manifest(root)

    assert manifest
    assert "logs" not in visited
    assert "logs/deep" not in visited
    assert "crash-reports" not in visited
    assert all(not row["path"].startswith("logs/") for row in manifest)


def test_manifest_scan_error_fails_closed(tmp_path, monkeypatch) -> None:
    root = tmp_path / "world"
    _fixture(root)

    def failing_walk(*args, **kwargs):
        kwargs["onerror"](PermissionError("denied"))
        if False:
            yield None

    monkeypatch.setattr(world_cut.os, "walk", failing_walk)
    with pytest.raises(world_cut.MinecraftWorldCutError) as captured:
        world_cut._tree_manifest(root)

    assert captured.value.code == "WORLD_SCAN_FAILED"
