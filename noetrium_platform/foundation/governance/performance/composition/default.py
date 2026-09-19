from __future__ import annotations

from pathlib import Path
from typing import Callable

from noetrium_platform.foundation.governance.api import (
    GovernanceBaselineApprovalSet,
    GovernanceBaselineLane,
    RepositorySourceIndexPort,
    RepositorySourcePort,
)
from noetrium_platform.foundation.governance.composition import (
    external_governance_baseline_approval_set,
    resolve_governance_source,
    verify_exact_lane_runtime,
)
from noetrium_platform.foundation.governance.performance.api import PerformanceSnapshot
from noetrium_platform.foundation.governance.performance.providers import (
    FilesystemPerformanceSnapshotStore,
    RepositoryPerformanceSourceInventory,
)
from noetrium_platform.foundation.governance.performance.runtime import (
    JavaScriptPerformanceAnalyzer,
    PerformanceGovernanceService,
    PerformanceScanner,
    PythonPerformanceAnalyzer,
    ShellPerformanceAnalyzer,
)
from noetrium_platform.foundation.governance.providers import GitRepositorySourceTree, RepositorySourceTree
from noetrium_platform.foundation.governance.runtime import governance_lane_implementation_digest


def _scanner(
    source: RepositorySourcePort,
    *,
    source_index: RepositorySourceIndexPort | None,
    implementation_digest: str,
) -> PerformanceScanner:
    authority = source_index.source_authority if source_index is not None else "filesystem"
    revision = source_index.source_revision if source_index is not None else None
    return PerformanceScanner(
        RepositoryPerformanceSourceInventory(source),
        (
            PythonPerformanceAnalyzer(source_index),
            JavaScriptPerformanceAnalyzer(),
            ShellPerformanceAnalyzer(),
        ),
        source_authority=authority,
        source_revision=revision,
        analyzer_implementation_digest=implementation_digest,
    )


def _baseline_replay_factory(
    root: Path,
    *,
    implementation_digest: str,
    git_executable: str | Path | None,
) -> Callable[[str], PerformanceSnapshot]:
    def replay(revision: str) -> PerformanceSnapshot:
        historical = GitRepositorySourceTree(
            root, revision=revision, git_executable=git_executable
        ).index()
        return _scanner(
            historical, source_index=historical, implementation_digest=implementation_digest
        ).scan()
    return replay


def build_performance_governance(
    root: Path,
    *,
    exact: bool = False,
    state_root: Path | None = None,
    source_inventory: RepositorySourcePort | None = None,
    source_index: RepositorySourceIndexPort | None = None,
    approval_set: GovernanceBaselineApprovalSet | None = None,
    git_executable: str | Path | None = None,
) -> PerformanceGovernanceService:
    root = Path(root).resolve()
    source, resolved_index = resolve_governance_source(
        root,
        exact=exact,
        source_inventory=source_inventory,
        source_index=source_index,
        git_executable=git_executable,
    )
    implementation_digest = (
        governance_lane_implementation_digest(resolved_index, GovernanceBaselineLane.PERFORMANCE)
        if resolved_index is not None else ""
    )
    replay = None
    if exact:
        assert resolved_index is not None
        filesystem_index = RepositorySourceTree(root).index()
        verify_exact_lane_runtime(
            root,
            runtime_package=Path(__file__).resolve().parents[1],
            relative_package="noetrium_platform/foundation/governance/performance",
            source_index=resolved_index,
            immutable_implementation_digest=implementation_digest,
            filesystem_implementation_digest=governance_lane_implementation_digest(
                filesystem_index, GovernanceBaselineLane.PERFORMANCE
            ),
        )
        replay = _baseline_replay_factory(
            root, implementation_digest=implementation_digest, git_executable=git_executable
        )
    state = Path(state_root) if state_root is not None else root / ".local" / "performance-governance"
    store = FilesystemPerformanceSnapshotStore(
        state, baseline_path=root / "docs" / "status" / "performance" / "PERFORMANCE_BASELINE.json"
    )
    return PerformanceGovernanceService(
        scanner=_scanner(
            source, source_index=resolved_index, implementation_digest=implementation_digest
        ),
        store=store,
        baseline_replay=replay,
        approval_set=approval_set if approval_set is not None else external_governance_baseline_approval_set(),
    )


__all__ = ["build_performance_governance"]
