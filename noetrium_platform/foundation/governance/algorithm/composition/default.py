from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from noetrium_platform.foundation.governance.algorithm.api import AlgorithmGovernanceApprovalSet, AlgorithmSnapshot
from noetrium_platform.foundation.governance.algorithm.providers import (
    FilesystemAlgorithmSnapshotStore,
    FilesystemFileAnalysisCache,
    RepositorySourceInventory,
    load_algorithm_governance_approval_set,
)
from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort, RepositorySourcePort
from noetrium_platform.foundation.governance.providers import GitRepositorySourceTree, RepositorySourceTree
from noetrium_platform.foundation.governance.algorithm.runtime import (
    AlgorithmGovernanceService,
    AlgorithmScanner,
    JavaScriptAlgorithmAnalyzer,
    PythonAlgorithmAnalyzer,
    ShellAlgorithmAnalyzer,
    algorithm_implementation_digest,
)


def _scanner(
    source: RepositorySourcePort,
    *,
    source_index: RepositorySourceIndexPort | None,
    cache: FilesystemFileAnalysisCache | None,
    use_cache: bool,
    implementation_digest: str,
) -> AlgorithmScanner:
    authority = source_index.source_authority if source_index is not None else "filesystem"
    revision = source_index.source_revision if source_index is not None else None
    return AlgorithmScanner(
        inventory=RepositorySourceInventory(source),
        analyzers=(
            PythonAlgorithmAnalyzer(source_index),
            JavaScriptAlgorithmAnalyzer(),
            ShellAlgorithmAnalyzer(),
        ),
        cache=cache,
        use_cache=use_cache,
        source_authority=authority,
        source_revision=revision,
        analyzer_implementation_digest=implementation_digest,
    )


def _external_approval_set() -> AlgorithmGovernanceApprovalSet | None:
    path = os.environ.get("NOETRIUM_ALGORITHM_GOVERNANCE_APPROVALS", "").strip()
    digest = os.environ.get("NOETRIUM_ALGORITHM_GOVERNANCE_APPROVALS_SHA256", "").strip()
    if bool(path) != bool(digest):
        raise ValueError("external algorithm governance approval path and SHA-256 must be provided together")
    if not path:
        return None
    return load_algorithm_governance_approval_set(Path(path), expected_sha256=digest)


def _resolve_source(
    root: Path,
    *,
    exact: bool,
    source_inventory: RepositorySourcePort | None,
    source_index: RepositorySourceIndexPort | None,
    git_executable: str | Path | None,
) -> tuple[RepositorySourcePort, RepositorySourceIndexPort | None]:
    if source_index is not None and source_inventory is not None and source_index is not source_inventory:
        raise ValueError("source_inventory and source_index must reference the same frozen source cut")
    if source_index is not None:
        return source_index, source_index
    if exact:
        if source_inventory is not None:
            raise ValueError("exact algorithm governance requires a RepositorySourceIndexPort, not an unbound inventory")
        resolved = GitRepositorySourceTree(root, git_executable=git_executable).index()
        return resolved, resolved
    return source_inventory or RepositorySourceTree(root), None


def _verify_exact_runtime(
    root: Path,
    source_index: RepositorySourceIndexPort,
    implementation_digest: str,
) -> None:
    runtime_package = Path(__file__).resolve().parents[1]
    expected_package = (root / "noetrium_platform" / "foundation" / "governance" / "algorithm").resolve()
    if runtime_package != expected_package:
        raise ValueError(
            "exact algorithm governance must execute the analyzer implementation from the audited repository root"
        )
    if source_index.source_authority != "git" or source_index.source_revision is None:
        raise ValueError("exact algorithm governance requires immutable Git source authority")
    filesystem_index = RepositorySourceTree(root).index()
    if algorithm_implementation_digest(filesystem_index) != implementation_digest:
        raise ValueError(
            "exact algorithm analyzer implementation bytes differ from the immutable source cut"
        )


def _baseline_replay_factory(
    root: Path,
    *,
    implementation_digest: str,
    git_executable: str | Path | None,
) -> Callable[[str], AlgorithmSnapshot]:
    def replay(revision: str) -> AlgorithmSnapshot:
        historical = GitRepositorySourceTree(
            root, revision=revision, git_executable=git_executable
        ).index()
        return _scanner(
            historical,
            source_index=historical,
            cache=None,
            use_cache=False,
            implementation_digest=implementation_digest,
        ).scan()
    return replay


def _resolved_approval_set(
    supplied: AlgorithmGovernanceApprovalSet | None,
) -> AlgorithmGovernanceApprovalSet | None:
    return supplied if supplied is not None else _external_approval_set()


def build_algorithm_governance(
    root: Path,
    *,
    exact: bool = False,
    state_root: Path | None = None,
    source_inventory: RepositorySourcePort | None = None,
    source_index: RepositorySourceIndexPort | None = None,
    approval_set: AlgorithmGovernanceApprovalSet | None = None,
    git_executable: str | Path | None = None,
) -> AlgorithmGovernanceService:
    root = Path(root).resolve()
    source, resolved_index = _resolve_source(
        root,
        exact=exact,
        source_inventory=source_inventory,
        source_index=source_index,
        git_executable=git_executable,
    )
    state = Path(state_root) if state_root is not None else root / ".local" / "algorithm-governance"
    cache = None if exact else FilesystemFileAnalysisCache(state / "cache")
    implementation_digest = algorithm_implementation_digest(resolved_index) if resolved_index is not None else ""
    baseline_replay = None
    if exact:
        assert resolved_index is not None
        _verify_exact_runtime(root, resolved_index, implementation_digest)
        baseline_replay = _baseline_replay_factory(
            root,
            implementation_digest=implementation_digest,
            git_executable=git_executable,
        )
    scanner = _scanner(
        source,
        source_index=resolved_index,
        cache=cache,
        use_cache=not exact,
        implementation_digest=implementation_digest,
    )
    store = FilesystemAlgorithmSnapshotStore(
        state,
        baseline_path=root / "docs" / "status" / "algorithm" / "ALGORITHM_BASELINE.json",
    )
    return AlgorithmGovernanceService(
        scanner=scanner,
        store=store,
        baseline_replay=baseline_replay,
        approval_set=_resolved_approval_set(approval_set),
    )


__all__ = ["build_algorithm_governance"]
