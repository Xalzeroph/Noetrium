from __future__ import annotations

"""Concurrent, fail-closed release evidence generation.

Regression and static quality are independent read-only consumers of the same
frozen source snapshot.  Running them concurrently removes fixed quality latency
from the critical path without weakening exact-repository binding: a second
manifest snapshot must match byte-for-byte before evidence can be emitted.
"""

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.governance.release.api import (
    ReleaseManifest,
    ReleaseQualityEvidence,
    ReleaseQualityEvidencePort,
    ReleaseRegressionEvidence,
    ReleaseRegressionPort,
)

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionLaneKind, ExecutionSpec, TaskContextPort, TaskGroupPort

from .evidence import ReleaseEvidence, build_release_evidence
from .manifest import build_release_manifest


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceGenerationResult:
    manifest: ReleaseManifest
    quality: ReleaseQualityEvidence
    regression: ReleaseRegressionEvidence
    evidence: ReleaseEvidence


class ReleaseEvidenceCoordinator:
    """Coordinate exact regression and quality checks over one source snapshot."""

    def __init__(
        self,
        *,
        quality: ReleaseQualityEvidencePort,
        regression: ReleaseRegressionPort,
        task_group: TaskGroupPort,
    ) -> None:
        self._quality = quality
        self._regression = regression
        self._task_group = task_group

    def generate(self, root: Path) -> ReleaseEvidenceGenerationResult:
        root = Path(root).resolve()
        baseline = build_release_manifest(root)

        # Quality and regression are independent read-only consumers of the same
        # frozen source snapshot.  Concurrency ownership lives in the platform
        # executor authority rather than this release runtime.
        def build_quality(context: TaskContextPort) -> ReleaseQualityEvidence:
            context.checkpoint()
            result = self._quality.build(root)
            context.checkpoint()
            return result

        quality_task = self._task_group.submit(
            ExecutionSpec(task_id="release-quality", lane_kind=ExecutionLaneKind.BLOCKING_IO),
            build_quality,
            deadline=Deadline.after(180.0),
        )
        regression = self._regression.run(
            root,
            source_manifest_digest=baseline.digest(),
        )
        quality = quality_task.result(timeout=180.0)

        final_manifest = build_release_manifest(
            root,
            platform_code_version=baseline.platform_code_version,
            python_requires=baseline.python_requires,
        )
        if final_manifest.digest() != baseline.digest():
            raise RuntimeError("source tree changed during regression/quality verification")

        evidence = build_release_evidence(
            root,
            quality=quality,
            regression_tests_collected=regression.tests_collected,
            regression_tests_passed=regression.tests_passed,
            regression_tests_skipped=regression.tests_skipped,
            regression_shard_count=regression.shard_count,
            regression_test_inventory_sha256=regression.test_inventory_sha256,
            regression_runtime_sha256=regression.runtime_sha256,
            regression_plan_sha256=regression.plan_sha256,
            manifest=final_manifest,
        )
        if not evidence.clean:
            raise RuntimeError("architecture/quality/regression evidence is not clean")
        return ReleaseEvidenceGenerationResult(
            manifest=final_manifest,
            quality=quality,
            regression=regression,
            evidence=evidence,
        )


__all__ = ["ReleaseEvidenceCoordinator", "ReleaseEvidenceGenerationResult"]
