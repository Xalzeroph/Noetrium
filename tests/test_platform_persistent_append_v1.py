from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel.durability import (
    AppendDurability,
    DurableAppendError,
    PersistentAppendFile,
    append_bytes,
)


def test_persistent_append_file_owns_exact_append_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "events.bin"
    stream = PersistentAppendFile(path)

    assert not stream.is_open
    stream.open()
    assert stream.is_open
    stream.write_all(b"alpha")
    stream.write_all(memoryview(b"-beta"))
    stream.sync()
    stream.close()
    assert not stream.is_open
    assert path.read_bytes() == b"alpha-beta"

    stream.close()
    with pytest.raises(RuntimeError, match="not open"):
        stream.write_all(b"late")


def test_exclusive_append_fails_closed_without_mutating_existing_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "segment.jsonl"
    append_bytes(
        path,
        b"first\n",
        durability=AppendDurability.BUFFERED,
        exclusive_create=True,
    )

    with pytest.raises(DurableAppendError):
        append_bytes(
            path,
            b"second\n",
            durability=AppendDurability.BUFFERED,
            exclusive_create=True,
        )

    assert path.read_bytes() == b"first\n"
