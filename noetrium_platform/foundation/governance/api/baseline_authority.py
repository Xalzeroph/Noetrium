from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Mapping


class GovernanceBaselineLane(StrEnum):
    CONCURRENCY = "concurrency"
    PERFORMANCE = "performance"


def governance_baseline_semantic_digest(
    *,
    lane: GovernanceBaselineLane,
    source_revision: str,
    source_digest: str,
    analyzer_revision: str,
    analyzer_implementation_digest: str,
    observed_blocker_fingerprints: Iterable[str],
    accepted_blocker_fingerprints: Iterable[str],
) -> str:
    """Return the canonical authority digest for a reviewed quality baseline."""
    payload = {
        "lane": lane.value,
        "source_revision": source_revision,
        "source_digest": source_digest,
        "analyzer_revision": analyzer_revision,
        "analyzer_implementation_digest": analyzer_implementation_digest,
        "observed_blocker_fingerprints": sorted(str(item) for item in observed_blocker_fingerprints),
        "accepted_blocker_fingerprints": sorted(str(item) for item in accepted_blocker_fingerprints),
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernanceBaselineApproval:
    approval_id: str
    lane: GovernanceBaselineLane
    source_git_sha: str
    source_digest: str
    analyzer_revision: str
    analyzer_implementation_digest: str
    baseline_digest: str
    decision: str
    authority: str
    scope: str
    review_state: str
    review_evidence_refs: tuple[str, ...]
    issued_at: str
    note: str
    approval_record_sha256: str

    @property
    def approved(self) -> bool:
        return self.decision == "approved"


@dataclass(frozen=True, slots=True)
class GovernanceBaselineApprovalSet:
    schema_version: str
    authority: str
    approvals: tuple[GovernanceBaselineApproval, ...]
    default_decision: str
    rule: str
    _index: Mapping[tuple[str, str, str, str, str, str], GovernanceBaselineApproval] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        approved = tuple(row for row in self.approvals if row.approved)
        index = {
            (
                row.lane.value,
                row.source_git_sha,
                row.source_digest,
                row.analyzer_revision,
                row.analyzer_implementation_digest,
                row.baseline_digest,
            ): row
            for row in approved
        }
        if len(index) != len(approved):
            raise ValueError("approved governance baseline identities must be unique")
        object.__setattr__(self, "_index", MappingProxyType(index))

    def approval_for(
        self,
        *,
        lane: GovernanceBaselineLane,
        source_git_sha: str,
        source_digest: str,
        analyzer_revision: str,
        analyzer_implementation_digest: str,
        baseline_digest: str,
    ) -> GovernanceBaselineApproval | None:
        return self._index.get((
            lane.value,
            source_git_sha,
            source_digest,
            analyzer_revision,
            analyzer_implementation_digest,
            baseline_digest,
        ))


__all__ = [
    "GovernanceBaselineApproval",
    "GovernanceBaselineApprovalSet",
    "GovernanceBaselineLane",
    "governance_baseline_semantic_digest",
]
