from __future__ import annotations

from pathlib import Path
import errno
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from noetrium_platform.infrastructure.reliability.forensics.providers.segmented_hashlog import SegmentedHashChainedJSONL
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog import HashChainError
from noetrium_platform.infrastructure.reliability.forensics.providers.directory_change_signal import DirectoryChangeSignal


class SegmentedEventHotPathV173Tests(unittest.TestCase):
    def test_steady_state_append_does_not_enumerate_all_segments(self) -> None:
        with TemporaryDirectory() as td:
            ledger = SegmentedHashChainedJSONL(
                Path(td) / "events",
                max_segment_bytes=128,
                fsync_every=4,
            )
            # First append initializes/verifies the writer state.
            ledger.append({"event": 0, "payload": "x" * 100})
            # Force multiple rotations so an O(segment-count) check would be visible.
            for value in range(1, 8):
                ledger.append({"event": value, "payload": "x" * 100})
            with patch.object(
                ledger,
                "_segment_files",
                side_effect=AssertionError("steady-state append enumerated segment directory"),
            ):
                ledger.append({"event": 9, "payload": "hot"})

    def test_external_segment_directory_change_still_fails_closed(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            ledger = SegmentedHashChainedJSONL(root, fsync_every=4)
            ledger.append({"event": 1})
            (root / "99999999.jsonl").write_text("", encoding="utf-8")
            with self.assertRaises(Exception):
                ledger.append({"event": 2})

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux shared-inotify contract")
    def test_linux_many_directory_signals_do_not_fall_back_to_stat(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            signals: list[DirectoryChangeSignal] = []
            try:
                for index in range(160):
                    root = base / f"watch-{index}"
                    root.mkdir()
                    signal = DirectoryChangeSignal(root)
                    signals.append(signal)
                    self.assertEqual(signal.mode, "inotify")
                for index, signal in enumerate(signals):
                    root = base / f"watch-{index}"
                    (root / "00000000.jsonl").write_bytes(b"x")
                    self.assertTrue(signal.wait_changed_since(None, timeout_seconds=0.25))
                    signal.acknowledge()
            finally:
                for signal in signals:
                    signal.close()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux shared-inotify contract")
    def test_linux_watch_registration_failure_is_fail_closed(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            root.mkdir()
            failure = OSError(errno.ENOSPC, "inotify watch quota exhausted", str(root))
            with patch(
                "noetrium_platform.infrastructure.reliability.forensics.providers.directory_change_signal.open_linux_directory_watch",
                side_effect=failure,
            ):
                with self.assertRaises(OSError) as raised:
                    DirectoryChangeSignal(root)
            self.assertEqual(raised.exception.errno, errno.ENOSPC)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux shared-inotify contract")
    def test_linux_same_directory_tokens_keep_independent_pending_latches(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            root.mkdir()
            first = DirectoryChangeSignal(root)
            second = DirectoryChangeSignal(root)
            try:
                (root / "00000000.jsonl").write_bytes(b"x")
                self.assertTrue(first.wait_changed_since(None, timeout_seconds=0.25))
                first.acknowledge()
                self.assertTrue(second.changed_since(None))
                second.acknowledge()
            finally:
                first.close()
                second.close()

    @unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os, "fork"), "Linux fork isolation")
    def test_linux_fork_child_uses_independent_inotify_instance(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            parent_root = base / "parent"; parent_root.mkdir()
            child_root = base / "child"; child_root.mkdir()
            parent_signal = DirectoryChangeSignal(parent_root)
            child_to_parent_r, child_to_parent_w = os.pipe()
            parent_to_child_r, parent_to_child_w = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(child_to_parent_r); os.close(parent_to_child_w)
                    child_signal = DirectoryChangeSignal(child_root)
                    os.write(child_to_parent_w, b"R")
                    if os.read(parent_to_child_r, 1) != b"G": os._exit(8)
                    (child_root / "00000000.jsonl").write_bytes(b"x")
                    os.write(child_to_parent_w, b"C")
                    if os.read(parent_to_child_r, 1) != b"K": os._exit(9)
                    observed = child_signal.wait_changed_since(None, timeout_seconds=0.25)
                    child_signal.close()
                    os._exit(0 if observed else 10)
                except BaseException:
                    os._exit(11)
            os.close(child_to_parent_w); os.close(parent_to_child_r)
            try:
                self.assertEqual(os.read(child_to_parent_r, 1), b"R")
                os.write(parent_to_child_w, b"G")
                self.assertEqual(os.read(child_to_parent_r, 1), b"C")
                self.assertFalse(parent_signal.changed_since(None))
                os.write(parent_to_child_w, b"K")
                _, status = os.waitpid(pid, 0)
                self.assertTrue(os.WIFEXITED(status))
                self.assertEqual(os.WEXITSTATUS(status), 0)
            finally:
                parent_signal.close()
                os.close(child_to_parent_r); os.close(parent_to_child_w)

    @unittest.skipUnless(sys.platform == "win32", "Windows change-notification contract")
    def test_windows_fresh_directory_creation_signal_has_zero_misses(self) -> None:
        with TemporaryDirectory() as td:
            base = Path(td)
            for index in range(500):
                root = base / f"watch-{index}"
                root.mkdir()
                signal = DirectoryChangeSignal(root)
                self.assertEqual(signal.mode, "windows-notify")
                (root / "99999999.jsonl").write_bytes(b"")
                self.assertTrue(signal.changed_since(None))
                signal.close()


    @unittest.skipUnless(sys.platform == "win32", "Windows change-notification contract")
    def test_windows_change_signal_detects_repeated_create_delete_rename(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            root.mkdir()
            signal = DirectoryChangeSignal(root)
            for index in range(100):
                path = root / f"entry-{index}.a"
                path.write_bytes(b"x")
                self.assertTrue(signal.changed_since(None)); signal.acknowledge()
                renamed = path.with_suffix(".b")
                path.rename(renamed)
                self.assertTrue(signal.changed_since(None)); signal.acknowledge()
                renamed.unlink()
                self.assertTrue(signal.changed_since(None)); signal.acknowledge()
            signal.close()


    def test_external_directory_mutation_during_active_append_fails_closed(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            ledger = SegmentedHashChainedJSONL(root, fsync_every=4)
            ledger.append({"event": 1})
            original = ledger._writer.append
            def inject(payload):
                receipt = original(payload)
                (root / "99999999.jsonl").write_bytes(b"")
                return receipt
            ledger._writer.append = inject
            with self.assertRaisesRegex(HashChainError, "during owning writer append"):
                ledger.append({"event": 2})

    def test_owned_segment_creation_does_not_mask_extra_directory_entry(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            ledger = SegmentedHashChainedJSONL(root, fsync_every=4)
            original = ledger._writer.append
            def inject(payload):
                receipt = original(payload)
                (root / "99999999.jsonl").write_bytes(b"")
                return receipt
            ledger._writer.append = inject
            with self.assertRaisesRegex(HashChainError, "namespace drift"):
                ledger.append({"event": 1})


    def test_owned_segment_creation_boundedly_waits_for_delayed_notification(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            ledger = SegmentedHashChainedJSONL(root, fsync_every=4)
            with patch.object(ledger._directory_signal, "changed_since", return_value=False), patch.object(
                ledger._directory_signal, "wait_changed_since", return_value=True
            ) as waited:
                ledger.append({"event": 1})
            waited.assert_called_once()
            self.assertEqual(ledger.cached_tail[0], 1)
            ledger.close()

    def test_owned_segment_creation_notification_timeout_fails_closed(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"
            ledger = SegmentedHashChainedJSONL(root, fsync_every=4)
            with patch.object(ledger._directory_signal, "changed_since", return_value=False), patch.object(
                ledger._directory_signal, "wait_changed_since", return_value=False
            ) as waited:
                with self.assertRaisesRegex(HashChainError, "was not observed"):
                    ledger.append({"event": 1})
            self.assertEqual(waited.call_count, 1)
            ledger.close()

    def test_directory_change_wait_rejects_non_finite_budget(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td) / "events"; root.mkdir()
            signal = DirectoryChangeSignal(root)
            with self.assertRaises(ValueError):
                signal.wait_changed_since(None, timeout_seconds=float("nan"))
            signal.close()


if __name__ == "__main__":
    unittest.main()
