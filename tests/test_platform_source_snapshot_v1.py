from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.composition.operator.project.platform_source_snapshot import (
    materialize_platform_source_snapshot,
)


def _source(root: Path) -> Path:
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname="snapshot-fixture"\nversion="1.0.0"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )
    package = root / "noetrium_platform"
    package.mkdir()
    (package / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "runner.py").write_text("print('v1')\n", encoding="utf-8")
    return root


def test_platform_source_snapshot_is_content_addressed_and_reused(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    store = tmp_path / "store"
    first = materialize_platform_source_snapshot(source, store)
    second = materialize_platform_source_snapshot(source, store)

    assert first == second
    assert first.root == store / first.source_tree_sha256
    assert (first.root / "noetrium_platform/runtime.py").read_text() == "VALUE = 1\n"
    assert first.file_count == 3
    assert first.total_bytes > 0


def test_platform_source_snapshot_remains_immutable_after_worktree_changes(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    store = tmp_path / "store"
    first = materialize_platform_source_snapshot(source, store)
    old_bytes = (first.root / "noetrium_platform/runtime.py").read_bytes()

    (source / "noetrium_platform/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = materialize_platform_source_snapshot(source, store)

    assert first.source_tree_sha256 != second.source_tree_sha256
    assert first.root != second.root
    assert (first.root / "noetrium_platform/runtime.py").read_bytes() == old_bytes
    assert (second.root / "noetrium_platform/runtime.py").read_text() == "VALUE = 2\n"


def test_platform_source_snapshot_rejects_symlinked_source_file(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    external = tmp_path / "external.py"
    external.write_text("SECRET = True\n", encoding="utf-8")
    linked = source / "noetrium_platform/linked.py"
    linked.symlink_to(external)

    with pytest.raises(RuntimeError, match="platform source changed while snapshotting"):
        materialize_platform_source_snapshot(source, tmp_path / "store")


def test_existing_snapshot_is_reverified_before_reuse(tmp_path: Path) -> None:
    source = _source(tmp_path / "source")
    store = tmp_path / "store"
    frozen = materialize_platform_source_snapshot(source, store)
    (frozen.root / "scripts/runner.py").write_text("print('tampered')\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="snapshot drifted"):
        materialize_platform_source_snapshot(source, store)
