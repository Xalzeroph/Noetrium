import os
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest

from scripts.release_regression import (
    ReleaseRegressionFailure,
    _decode_diagnostic_output,
    _parse_collected,
    _parse_result,
    _run_pytest,
)


class ReleaseRegressionV191Tests(unittest.TestCase):
    def test_collection_and_result_parsing_are_machine_checked(self):
        self.assertEqual(_parse_collected("665 tests collected in 0.5s\n"), 665)
        self.assertEqual(_parse_result("665 passed, 4 subtests passed in 30s\n"), (665, 0))
        self.assertEqual(_parse_result("660 passed, 5 skipped in 30s\n"), (660, 5))

    def test_unparseable_regression_output_fails_closed(self):
        with self.assertRaises(ReleaseRegressionFailure):
            _parse_collected("collection complete")
        with self.assertRaises(ReleaseRegressionFailure):
            _parse_result("all good")


    def test_pytest_diagnostic_log_tolerates_non_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_bytes.py").write_text(
                "import os, sys\n"
                "os.write(sys.stdout.fileno(), b'\\xbe')\n"
                "def test_ok():\n"
                "    assert True\n",
                encoding="utf-8",
            )
            output = _run_pytest(root, ["-q"], timeout_seconds=30.0)
            self.assertIn("1 passed", output)

        self.assertEqual(_decode_diagnostic_output(b"prefix\xbe"), "prefix\ufffd")

    def test_machine_readable_pytest_result_is_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            evidence = __import__("scripts.release_regression", fromlist=["_run_pytest_shard"])._run_pytest_shard(
                root, ["-q", "test_ok.py"], timeout_seconds=30.0
            )
            self.assertEqual(evidence.tests_collected, 1)
            self.assertEqual(evidence.passed, 1)
            self.assertEqual(evidence.skipped, 0)

    def test_machine_result_rejects_xfail_in_release_inventory(self):
        import scripts.release_regression as regression
        evidence = regression._PytestShardEvidence(
            schema_version=1, tests_collected=1, passed=0, skipped=0, failed=0,
            xfailed=1, xpassed=0, collection_errors=0, deselected=0,
            pytest_exitstatus=0, duration_seconds=0.01,
        )
        with self.assertRaises(ReleaseRegressionFailure):
            evidence.validate_release_clean()

    def test_pytest_shard_reaps_descendants_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "child.pid"
            (root / "test_spawn.py").write_text(
                "import subprocess, sys\n"
                "def test_spawn():\n"
                f"    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"    open({str(pid_path)!r}, 'w').write(str(p.pid))\n"
                "    assert True\n",
                encoding="utf-8",
            )
            output = _run_pytest(root, ["-q"], timeout_seconds=10.0)
            self.assertIn("1 passed", output)
            child_pid = int(pid_path.read_text())
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and Path(f"/proc/{child_pid}").exists():
                stat = Path(f"/proc/{child_pid}/stat")
                if stat.exists() and stat.read_text().split()[2] == "Z":
                    break
                time.sleep(0.02)
            if Path(f"/proc/{child_pid}/stat").exists():
                self.assertEqual(Path(f"/proc/{child_pid}/stat").read_text().split()[2], "Z")

    def test_pytest_timeout_reaps_entire_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "child.pid"
            (root / "test_spawn.py").write_text(
                "import subprocess, sys, time\n"
                f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"open({str(pid_path)!r}, 'w').write(str(p.pid))\n"
                "def test_spawn():\n"
                "    time.sleep(60)\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseRegressionFailure):
                _run_pytest(root, ["-q"], timeout_seconds=15.0)
            child_pid = int(pid_path.read_text())
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and Path(f"/proc/{child_pid}").exists():
                stat = Path(f"/proc/{child_pid}/stat")
                if stat.exists() and stat.read_text().split()[2] == "Z":
                    break
                time.sleep(0.02)
            if Path(f"/proc/{child_pid}/stat").exists():
                self.assertEqual(Path(f"/proc/{child_pid}/stat").read_text().split()[2], "Z")

    @unittest.skipIf(os.name == "nt", "POSIX external-signal cleanup contract; Windows tree cleanup is covered by timeout/reaper tests")
    def test_external_runner_sigterm_reaps_active_pytest_group(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shard_pid_path = root / "shard.pid"
            (root / "test_wait.py").write_text(
                "import os, time\n"
                f"open({str(shard_pid_path)!r}, 'w').write(str(os.getpid()))\n"
                "def test_wait():\n"
                "    time.sleep(60)\n",
                encoding="utf-8",
            )
            code = (
                "from pathlib import Path; "
                "from scripts.release_regression import _run_pytest; "
                f"_run_pytest(Path({str(root)!r}), ['-q'], timeout_seconds=60)"
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root)
            runner = subprocess.Popen(
                [sys.executable, "-c", code], cwd=project_root, env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline and not shard_pid_path.exists():
                    time.sleep(0.02)
                self.assertTrue(shard_pid_path.exists(), "pytest shard did not start")
                shard_pid = int(shard_pid_path.read_text())
                if os.name == "nt":
                    runner.send_signal(signal.CTRL_BREAK_EVENT)
                    expected_signal = signal.SIGBREAK
                else:
                    runner.send_signal(signal.SIGTERM)
                    expected_signal = signal.SIGTERM
                self.assertEqual(runner.wait(timeout=5.0), 128 + expected_signal)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and Path(f"/proc/{shard_pid}").exists():
                    stat = Path(f"/proc/{shard_pid}/stat")
                    if stat.exists() and stat.read_text().split()[2] == "Z":
                        break
                    time.sleep(0.02)
                if Path(f"/proc/{shard_pid}/stat").exists():
                    self.assertEqual(Path(f"/proc/{shard_pid}/stat").read_text().split()[2], "Z")
            finally:
                if runner.poll() is None:
                    runner.kill()
                    runner.wait()


if __name__ == "__main__":
    unittest.main()
