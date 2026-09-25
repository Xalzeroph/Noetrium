from __future__ import annotations

from pathlib import Path
import tempfile
import threading

import pytest

from noetrium_platform.foundation.governance.release.api import ReleaseQualityEvidence, ReleaseRegressionEvidence
from noetrium_platform.foundation.governance.release.runtime.generation import ReleaseEvidenceCoordinator
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime


def _tree(root: Path) -> None:
    (root / "noetrium_platform").mkdir(parents=True)
    (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
    (root / "noetrium_platform" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="1.2.3"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )


def _quality() -> ReleaseQualityEvidence:
    return ReleaseQualityEvidence(
        architecture_report_sha256="a" * 64,
        architecture_clean=True,
        no_degradation_findings=0,
        silent_failure_findings=0,
        algorithm_source_digest="b" * 64,
        algorithm_clean=True,
        algorithm_blockers=0,
        concurrency_source_digest="c" * 64,
        concurrency_clean=True,
        concurrency_blockers=0,
        performance_source_digest="d" * 64,
        performance_clean=True,
        performance_blockers=0,
    )


def _regression() -> ReleaseRegressionEvidence:
    return ReleaseRegressionEvidence(
        tests_collected=3,
        tests_passed=3,
        tests_skipped=0,
        shard_count=1,
        test_inventory_sha256="c" * 64,
        runtime_sha256="d" * 64,
        plan_sha256="e" * 64,
    )


def _runtime():
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=8,
        ),
        blocking_io_thread_name_prefix="release-coordinator-test",
        timer_name="release-coordinator-test-timer",
    )


def test_quality_and_regression_overlap_but_bind_one_exact_snapshot():
    barrier = threading.Barrier(2, timeout=2.0)

    class Quality:
        def build(self, _root: Path):
            barrier.wait()
            return _quality()

    class Regression:
        def run(self, _root: Path, *, source_manifest_digest: str):
            assert len(source_manifest_digest) == 64
            barrier.wait()
            return _regression()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root)
        runtime = _runtime()
        group = runtime.open_task_group("release-coordinator")
        try:
            result = ReleaseEvidenceCoordinator(
                quality=Quality(),
                regression=Regression(),
                task_group=group,
            ).generate(root)
        finally:
            runtime.close()
        assert result.evidence.clean
        assert result.evidence.release_manifest_digest == result.manifest.digest()
        assert result.regression.tests_passed == 3


def test_source_drift_during_concurrent_verification_fails_closed():
    quality_started = threading.Event()
    mutation_done = threading.Event()

    class Quality:
        def build(self, root: Path):
            quality_started.set()
            (root / "noetrium_platform" / "x.py").write_text("x = 2\n", encoding="utf-8")
            mutation_done.set()
            return _quality()

    class Regression:
        def run(self, _root: Path, *, source_manifest_digest: str):
            assert len(source_manifest_digest) == 64
            assert quality_started.wait(2.0)
            assert mutation_done.wait(2.0)
            return _regression()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root)
        runtime = _runtime()
        group = runtime.open_task_group("release-coordinator-drift")
        try:
            with pytest.raises(RuntimeError, match="source tree changed"):
                ReleaseEvidenceCoordinator(
                    quality=Quality(),
                    regression=Regression(),
                    task_group=group,
                ).generate(root)
        finally:
            runtime.close()
