from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scripts.release_regression as regression
from noetrium_platform.foundation.governance.release.runtime.regression_state import default_regression_state_path


class ReleaseRegressionResumeV193Tests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        tests = root / "tests"
        tests.mkdir(parents=True)
        (tests / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        (tests / "test_b.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")

    @staticmethod
    def _fake_shard(_root: Path, args: list[str], **_kwargs):
        selected = [item for item in args if item.endswith(".py")]
        if len(selected) != 1:
            raise AssertionError(f"unexpected pytest args: {args}")
        return regression._PytestShardEvidence(
            schema_version=1,
            tests_collected=1,
            passed=1,
            skipped=0,
            failed=0,
            xfailed=0,
            xpassed=0,
            collection_errors=0,
            deselected=0,
            pytest_exitstatus=0,
            duration_seconds=0.01,
        )

    def test_completed_shards_resume_without_any_pytest_reexecution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            state_path = default_regression_state_path(root)
            with patch.object(regression, "_run_pytest_shard", side_effect=self._fake_shard):
                first = regression.run_release_regression(
                    root,
                    source_manifest_digest="a" * 64,
                    shard_size=1,
                    state_path=state_path,
                )

            with patch.object(regression, "_run_pytest_shard", side_effect=AssertionError("completed shard was re-executed")) as run:
                resumed = regression.run_release_regression(
                    root,
                    source_manifest_digest="a" * 64,
                    shard_size=1,
                    state_path=state_path,
                )
            self.assertEqual(resumed, first)
            run.assert_not_called()

    def test_source_manifest_change_invalidates_cached_shards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            state_path = default_regression_state_path(root)
            with patch.object(regression, "_run_pytest_shard", side_effect=self._fake_shard):
                regression.run_release_regression(
                    root,
                    source_manifest_digest="a" * 64,
                    shard_size=1,
                    state_path=state_path,
                )

            with patch.object(regression, "_run_pytest_shard", side_effect=self._fake_shard) as run:
                regression.run_release_regression(
                    root,
                    source_manifest_digest="b" * 64,
                    shard_size=1,
                    state_path=state_path,
                )
            self.assertEqual(run.call_count, 2)

    def test_corrupt_resume_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            state_path = default_regression_state_path(root)
            state_path.write_bytes(b"not-json")
            with patch.object(regression, "_run_pytest_shard", side_effect=self._fake_shard):
                with self.assertRaises(regression.ReleaseRegressionFailure):
                    regression.run_release_regression(
                        root,
                        source_manifest_digest="a" * 64,
                        shard_size=1,
                        state_path=state_path,
                    )

    def test_frozen_plan_is_reused_even_if_timing_history_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            state_path = default_regression_state_path(root)
            with patch.object(regression, "_run_pytest_shard", side_effect=self._fake_shard):
                first = regression.run_release_regression(
                    root, source_manifest_digest="a" * 64, shard_size=1, state_path=state_path
                )
            timing_path = regression.default_timing_history_path(root)
            timing_path.write_text(
                '{"schema_version":1,"files":{"tests/test_a.py":{"ewma_seconds":999.0,"samples":9}}}',
                encoding="utf-8",
            )
            with patch.object(regression, "_run_pytest_shard", side_effect=AssertionError("frozen plan re-executed")):
                resumed = regression.run_release_regression(
                    root, source_manifest_digest="a" * 64, shard_size=1, state_path=state_path
                )
            self.assertEqual(resumed.plan_sha256, first.plan_sha256)

    def test_semantically_tampered_frozen_plan_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            state_path = default_regression_state_path(root)
            with patch.object(regression, "_run_pytest_shard", side_effect=self._fake_shard):
                regression.run_release_regression(
                    root, source_manifest_digest="a" * 64, shard_size=1, state_path=state_path
                )
            import json
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            payload["planned_shards"] = payload["planned_shards"][:1]
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(regression.ReleaseRegressionFailure):
                regression.run_release_regression(
                    root, source_manifest_digest="a" * 64, shard_size=1, state_path=state_path
                )

    def test_exclusive_planner_bounds_shards_by_advisory_runtime_without_reordering(self):
        from noetrium_platform.foundation.governance.release.runtime.regression_timing import (
            FileTiming,
            ReleaseRegressionTimingHistory,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            tests = root / "tests"
            tests.mkdir(parents=True)
            files = []
            timings = {}
            for index in range(6):
                path = tests / f"test_{index}.py"
                path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
                files.append(path)
                timings[path.relative_to(root).as_posix()] = FileTiming(9.0, 1)
            history = ReleaseRegressionTimingHistory(1, timings)
            groups = regression._bounded_exclusive_groups(
                root,
                tuple(files),
                shard_size=32,
                timing_history=history,
                target_seconds=20.0,
            )

        self.assertEqual(groups, (tuple(files[:2]), tuple(files[2:4]), tuple(files[4:])))
        self.assertEqual(tuple(path for group in groups for path in group), tuple(files))

    def test_exclusive_planner_allows_one_oversized_file_without_empty_shard(self):
        from noetrium_platform.foundation.governance.release.runtime.regression_timing import (
            FileTiming,
            ReleaseRegressionTimingHistory,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            tests = root / "tests"
            tests.mkdir(parents=True)
            slow = tests / "test_slow.py"
            fast = tests / "test_fast.py"
            for path in (slow, fast):
                path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            history = ReleaseRegressionTimingHistory(
                1,
                {
                    slow.relative_to(root).as_posix(): FileTiming(30.0, 1),
                    fast.relative_to(root).as_posix(): FileTiming(1.0, 1),
                },
            )
            groups = regression._bounded_exclusive_groups(
                root,
                (slow, fast),
                shard_size=32,
                timing_history=history,
                target_seconds=20.0,
            )

        self.assertEqual(groups, ((slow,), (fast,)))

    def test_parallel_worker_count_is_bounded_by_cpu_and_explicit_cap(self):
        with patch.dict("os.environ", {"RELEASE_MAX_PARALLEL_WORKERS": "2"}, clear=False):
            with patch.object(regression.os, "cpu_count", return_value=8):
                self.assertEqual(regression._parallel_worker_count(7), 2)
        with patch.dict("os.environ", {"RELEASE_MAX_PARALLEL_WORKERS": "9"}, clear=False):
            with patch.object(regression.os, "cpu_count", return_value=3):
                self.assertEqual(regression._parallel_worker_count(7), 3)


if __name__ == "__main__":
    unittest.main()
