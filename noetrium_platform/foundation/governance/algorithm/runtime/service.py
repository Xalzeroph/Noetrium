from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmDiff,
    AlgorithmGateReport,
    AlgorithmGovernanceApprovalSet,
    AlgorithmSnapshot,
)
from noetrium_platform.foundation.governance.algorithm.api.ports import AlgorithmSnapshotStorePort
from .diff import gate_against_baseline
from .provenance import (
    algorithm_snapshot_semantic_digest,
    baseline_provenance_blocker,
    exact_snapshot_provenance_error,
)
from .scanner import AlgorithmScanner


class AlgorithmBaselineMissing(RuntimeError):
    pass


class AlgorithmBaselineApprovalMissing(RuntimeError):
    pass


def _empty_diff() -> AlgorithmDiff:
    return AlgorithmDiff(added=(), removed=(), changed=(), moved=())


@dataclass(slots=True)
class AlgorithmGovernanceService:
    scanner: AlgorithmScanner
    store: AlgorithmSnapshotStorePort
    baseline_replay: Callable[[str], AlgorithmSnapshot] | None = None
    approval_set: AlgorithmGovernanceApprovalSet | None = None

    def scan(self, *, persist: bool = True) -> AlgorithmSnapshot:
        snapshot = self.scanner.scan()
        if persist:
            self.store.publish_current(snapshot)
            self.store.append_history(snapshot)
        return snapshot

    def _historical_baseline_candidate(
        self, current: AlgorithmSnapshot, source_revision: str | None,
    ) -> AlgorithmSnapshot:
        if not source_revision:
            raise AlgorithmBaselineApprovalMissing(
                "exact algorithm baseline acceptance requires an explicit historical source revision"
            )
        if self.baseline_replay is None:
            raise AlgorithmBaselineApprovalMissing("algorithm baseline replay is unavailable")
        snapshot = self.baseline_replay(source_revision)
        error = exact_snapshot_provenance_error(snapshot, label="candidate algorithm baseline")
        if error is not None:
            raise AlgorithmBaselineApprovalMissing(error)
        if (snapshot.analyzer_revision, snapshot.analyzer_implementation_digest) != (
            current.analyzer_revision, current.analyzer_implementation_digest
        ):
            raise AlgorithmBaselineApprovalMissing(
                "candidate algorithm baseline does not use the running reviewed analyzer identity"
            )
        return snapshot

    def _require_baseline_approval(self, snapshot: AlgorithmSnapshot) -> None:
        assert snapshot.source_revision is not None
        approval = (
            self.approval_set.baseline_approval_for(
                source_git_sha=snapshot.source_revision,
                source_digest=snapshot.source_digest,
                analyzer_revision=snapshot.analyzer_revision,
                analyzer_implementation_digest=snapshot.analyzer_implementation_digest,
                snapshot_digest=algorithm_snapshot_semantic_digest(snapshot),
            )
            if self.approval_set is not None else None
        )
        if approval is None:
            raise AlgorithmBaselineApprovalMissing(
                "ROLE00 exact algorithm baseline approval is missing for this source/analyzer/snapshot identity"
            )

    def accept_baseline(self, *, source_revision: str | None = None) -> AlgorithmSnapshot:
        current = self.scan(persist=False)
        if current.source_authority == "git":
            snapshot = self._historical_baseline_candidate(current, source_revision)
            self._require_baseline_approval(snapshot)
        else:
            if source_revision is not None:
                raise AlgorithmBaselineApprovalMissing(
                    "historical source revision is only valid for Git-authoritative baseline acceptance"
                )
            snapshot = self.scan(persist=True)
        self.store.publish_baseline(snapshot)
        return snapshot

    def gate(self) -> tuple[AlgorithmSnapshot, AlgorithmGateReport]:
        baseline = self.store.load_baseline()
        if baseline is None:
            raise AlgorithmBaselineMissing("algorithm baseline is missing; reviewed baseline required")
        current = self.scan(persist=True)
        if current.source_authority == "git":
            blocker = baseline_provenance_blocker(
                baseline, current, replay=self.baseline_replay
            )
            if blocker is not None:
                return current, AlgorithmGateReport(
                    passed=False, blockers=(blocker,), warnings=(), diff=_empty_diff()
                )
        return current, gate_against_baseline(
            baseline, current, approval_set=self.approval_set
        )


__all__ = [
    "AlgorithmBaselineApprovalMissing",
    "AlgorithmBaselineMissing",
    "AlgorithmGovernanceService",
]
