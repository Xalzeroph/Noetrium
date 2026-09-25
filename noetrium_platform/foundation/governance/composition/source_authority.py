from __future__ import annotations

import os
from pathlib import Path

from noetrium_platform.foundation.governance.api import (
    GovernanceBaselineApprovalSet,
    RepositorySourceIndexPort,
    RepositorySourcePort,
)
from noetrium_platform.foundation.governance.providers import (
    GitRepositorySourceTree,
    RepositorySourceTree,
    load_governance_baseline_approval_set,
)


def resolve_governance_source(
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
            raise ValueError("exact governance requires a RepositorySourceIndexPort, not an unbound inventory")
        resolved = GitRepositorySourceTree(root, git_executable=git_executable).index()
        return resolved, resolved
    return source_inventory or RepositorySourceTree(root), None


def verify_exact_lane_runtime(
    root: Path,
    *,
    runtime_package: Path,
    relative_package: str,
    source_index: RepositorySourceIndexPort,
    immutable_implementation_digest: str,
    filesystem_implementation_digest: str,
) -> None:
    expected_package = (root / relative_package).resolve()
    if runtime_package.resolve() != expected_package:
        raise ValueError("exact governance must execute the analyzer implementation from the audited repository root")
    if source_index.source_authority != "git" or source_index.source_revision is None:
        raise ValueError("exact governance requires immutable Git source authority")
    if filesystem_implementation_digest != immutable_implementation_digest:
        raise ValueError("exact governance analyzer implementation differs from the immutable source cut")


def external_governance_baseline_approval_set() -> GovernanceBaselineApprovalSet | None:
    path = os.environ.get("NOETRIUM_GOVERNANCE_BASELINE_APPROVALS", "").strip()
    digest = os.environ.get("NOETRIUM_GOVERNANCE_BASELINE_APPROVALS_SHA256", "").strip()
    if bool(path) != bool(digest):
        raise ValueError("external governance baseline approval path and SHA-256 must be provided together")
    if not path:
        return None
    return load_governance_baseline_approval_set(Path(path), expected_sha256=digest)


__all__ = [
    "external_governance_baseline_approval_set",
    "resolve_governance_source",
    "verify_exact_lane_runtime",
]
