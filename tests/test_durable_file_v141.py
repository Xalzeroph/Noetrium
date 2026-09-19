from __future__ import annotations

from pathlib import Path
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    DurableFileWriteError,
    atomic_replace_bytes,
    durable_replace_file,
    durable_unlink,
)


class DurableFileTests(unittest.TestCase):
    def test_atomic_replace_fsyncs_parent_after_replace(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            events: list[str] = []

            from noetrium_platform.foundation.kernel.kernel.durability import durable_file as module

            real_replace = module.os.replace
            real_fsync_directory = module.fsync_directory

            def replace(src: Path, dst: Path) -> None:
                events.append("replace")
                real_replace(src, dst)

            def fsync_parent(parent: Path) -> None:
                events.append("fsync-parent")
                real_fsync_directory(parent)

            with patch.object(module.os, "replace", side_effect=replace), patch.object(
                module, "fsync_directory", side_effect=fsync_parent
            ):
                atomic_replace_bytes(path, b"v1")

            self.assertEqual(path.read_bytes(), b"v1")
            self.assertEqual(events, ["replace", "fsync-parent"])

    def test_failed_replace_does_not_leave_temp_file(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "state.json"
            with patch(
                "noetrium_platform.foundation.kernel.kernel.durability.durable_file.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(DurableFileWriteError):
                    atomic_replace_bytes(path, b"v1")

            self.assertFalse(path.exists())
            self.assertEqual(list(root.glob(".state.json.tmp.*")), [])

    def test_durable_replace_file_fsyncs_source_then_parent(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            source = root / "rebuilt.sqlite3"
            target = root / "index.sqlite3"
            source.write_bytes(b"sqlite")
            from noetrium_platform.foundation.kernel.kernel.durability import durable_file as module
            real_flush = module._flush_file
            flushed: list[Path] = []

            def flush(path: Path) -> None:
                flushed.append(path)
                real_flush(path)

            with patch.object(module, "_flush_file", side_effect=flush), patch.object(
                module, "fsync_directory"
            ) as sync:
                durable_replace_file(source, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), b"sqlite")
            self.assertEqual(flushed, [source])
            sync.assert_called_once_with(root)

    @unittest.skipUnless(os.name == "nt", "Windows sharing-violation semantics")
    def test_durable_replace_retries_transient_windows_sharing_violation(self) -> None:
        with TemporaryDirectory() as td:
            from noetrium_platform.foundation.kernel.kernel.durability import durable_file as module

            root = Path(td)
            source = root / "source.bin"
            target = root / "target.bin"
            source.write_bytes(b"payload")
            real_replace = module.os.replace
            attempts = 0

            def flaky_replace(src: Path, dst: Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    error = PermissionError("transient sharing violation")
                    error.winerror = 32
                    raise error
                real_replace(src, dst)

            with patch.object(module.os, "replace", side_effect=flaky_replace):
                durable_replace_file(source, target)

            self.assertEqual(attempts, 2)
            self.assertEqual(target.read_bytes(), b"payload")

    @unittest.skipUnless(os.name == "nt", "Windows sharing-violation semantics")
    def test_windows_retry_does_not_retry_non_sharing_permission_error(self) -> None:
        from noetrium_platform.foundation.kernel.kernel.durability import durable_file as module

        attempts = 0

        def denied() -> None:
            nonlocal attempts
            attempts += 1
            error = PermissionError("access denied")
            error.winerror = 5
            raise error

        with self.assertRaises(PermissionError):
            module._windows_file_operation(denied)
        self.assertEqual(attempts, 1)

    def test_durable_unlink_fsyncs_parent(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "lease.json"
            path.write_bytes(b"lease")
            with patch(
                "noetrium_platform.foundation.kernel.kernel.durability.durable_file.fsync_directory"
            ) as sync:
                durable_unlink(path)
            self.assertFalse(path.exists())
            sync.assert_called_once_with(root)


if __name__ == "__main__":
    unittest.main()
