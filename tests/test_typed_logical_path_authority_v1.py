from __future__ import annotations

import os
from pathlib import Path
from threading import Event, Thread

import pytest

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock
from noetrium_platform.foundation.kernel.kernel.logical_path import logical_absolute_path
from noetrium_platform.foundation.scope.path.api import PathFlavor
from noetrium_platform.foundation.scope.path.runtime.resolver import TargetPathResolver


def _expected(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def test_logical_absolute_path_never_dereferences_live_leaf(tmp_path: Path, monkeypatch) -> None:
    requested = tmp_path / "events.jsonl"
    redirected = tmp_path / "events.jsonl.1"
    monkeypatch.setattr(Path, "resolve", lambda self, **_: redirected)

    assert logical_absolute_path(requested) == _expected(requested)


def test_native_target_path_normalization_is_purely_lexical(tmp_path: Path, monkeypatch) -> None:
    requested = tmp_path / "artifact.bin"
    redirected = tmp_path / "artifact.bin.1"
    monkeypatch.setattr(Path, "resolve", lambda self, **_: redirected)

    normalized = TargetPathResolver().normalize(requested, flavor=PathFlavor.NATIVE)

    assert normalized == str(_expected(requested))


def test_interprocess_lock_identity_never_dereferences_guard_leaf(tmp_path: Path, monkeypatch) -> None:
    requested = tmp_path / "events.jsonl.guard.lock"
    redirected = tmp_path / "events.jsonl.1.guard.lock"
    monkeypatch.setattr(Path, "resolve", lambda self, **_: redirected)

    identity = InterprocessFileLock._canonical_windows_path_identity(requested)
    expected = str(_expected(requested)).replace("/", "\\").casefold()

    assert identity == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows mutex identity is platform-specific")
def test_interprocess_lock_identity_is_stable_during_guard_rename(tmp_path: Path) -> None:
    requested = tmp_path / "events.jsonl.guard.lock"
    rotated = tmp_path / "events.jsonl.1.guard.lock"
    requested.touch()
    stop = Event()

    def rotate() -> None:
        while not stop.is_set():
            try:
                if requested.exists():
                    os.replace(requested, rotated)
                if rotated.exists():
                    os.replace(rotated, requested)
            except OSError:
                pass

    thread = Thread(target=rotate)
    thread.start()
    try:
        expected = InterprocessFileLock._canonical_windows_path_identity(requested)
        for _ in range(20_000):
            assert InterprocessFileLock._canonical_windows_path_identity(requested) == expected
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="Windows final-path lookup is platform-specific")
def test_logical_absolute_path_is_stable_during_leaf_rename(tmp_path: Path) -> None:
    requested = tmp_path / "events.jsonl"
    rotated = tmp_path / "events.jsonl.1"
    requested.write_bytes(b"x")
    stop = Event()

    def rotate() -> None:
        while not stop.is_set():
            try:
                if requested.exists():
                    os.replace(requested, rotated)
                if rotated.exists():
                    os.replace(rotated, requested)
            except OSError:
                pass

    thread = Thread(target=rotate)
    thread.start()
    try:
        expected = _expected(requested)
        for _ in range(20_000):
            assert logical_absolute_path(requested) == expected
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
