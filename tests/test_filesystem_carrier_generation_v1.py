from __future__ import annotations

from pathlib import Path

import pytest

import noetrium_platform.foundation.kernel.kernel.durability.filesystem_generation as fs_generation
from noetrium_platform.foundation.kernel.kernel.durability import (
    FilesystemCarrierKind,
    capture_filesystem_carrier_generation,
    purge_directory_contents,
    remove_empty_directory_carrier,
    rename_directory_carrier,
)


def _generation(path: Path):
    return capture_filesystem_carrier_generation(
        path,
        expected_kind=FilesystemCarrierKind.DIRECTORY,
    )


def test_directory_carrier_rename_binds_same_object(tmp_path: Path) -> None:
    source = tmp_path / "live"
    source.mkdir()
    (source / "payload").write_bytes(b"owned")
    before = _generation(source)
    destination = tmp_path / "quarantine"

    moved = rename_directory_carrier(
        source,
        destination,
        expected_generation=before,
    )

    assert not source.exists()
    assert destination.is_dir()
    assert before.same_object(moved)
    assert (destination / "payload").read_bytes() == b"owned"


def test_directory_content_purge_is_retryable_without_removing_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "carrier"
    root.mkdir()
    first = root / "a"
    first.write_bytes(b"a")
    nested = root / "nested"
    nested.mkdir()
    (nested / "b").write_bytes(b"b")
    generation = _generation(root)
    real_rmtree = fs_generation.shutil.rmtree
    calls = 0

    def fail_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated descendant purge interruption")
        real_rmtree(path)

    monkeypatch.setattr(fs_generation.shutil, "rmtree", fail_once)
    with pytest.raises(OSError, match="descendant purge"):
        purge_directory_contents(
            root,
            expected_generation=generation,
        )

    assert root.is_dir()
    assert generation.same_object(_generation(root))

    monkeypatch.setattr(fs_generation.shutil, "rmtree", real_rmtree)
    emptied = purge_directory_contents(
        root,
        expected_generation=generation,
    )
    assert root.is_dir()
    assert tuple(root.iterdir()) == ()
    assert generation.same_object(emptied)

    assert remove_empty_directory_carrier(
        root,
        expected_generation=emptied,
    )
    assert not root.exists()


def test_empty_root_removal_rejects_same_path_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "carrier"
    root.mkdir()
    (root / "payload").write_bytes(b"owned")
    generation = _generation(root)
    emptied = purge_directory_contents(
        root,
        expected_generation=generation,
    )

    original = tmp_path / "original-generation"
    root.rename(original)
    root.mkdir()

    with pytest.raises(RuntimeError, match="generation changed"):
        remove_empty_directory_carrier(
            root,
            expected_generation=emptied,
        )

    assert root.is_dir()
    assert original.is_dir()
