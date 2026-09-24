"""Lightweight branch-lineage identities for intra-workload execution search.

This module does not replace the research workload checkpoint subsystem.
``WorkloadExecutionCut`` owns durable task-boundary capture/restore and component
payload consistency; these values only bind independently owned state digests to
one logical branch source without taking ownership of those payloads.
"""

from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest


_HEX_SHA256 = frozenset("0123456789abcdef")


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"execution lineage {name} is required")
    return value


def _require_sha256(name: str, value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in _HEX_SHA256 for char in value)
    ):
        raise ValueError(f"execution lineage {name} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionStateAnchor:
    """Content identity for one authority-owned piece of execution state.

    The platform records identity and integrity only. State bytes remain owned by
    the authority that produced the digest (for example an environment provider,
    agent checkpoint codec, or a downstream method). The ``authority`` string is
    descriptive provenance, not a dispatch key.
    """

    authority: str
    state_id: str
    sha256: str

    def __post_init__(self) -> None:
        _require_text("anchor authority", self.authority)
        _require_text("anchor state_id", self.state_id)
        _require_sha256("anchor sha256", self.sha256)

    def to_payload(self) -> dict[str, str]:
        return {
            "authority": self.authority,
            "state_id": self.state_id,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ExecutionSourceCut:
    """Immutable logical cut from which an execution branch may be derived.

    A cut binds independently owned state identities under one lineage identity.
    It deliberately does *not* claim that providers captured their state in one
    physical transaction. Callers that require stronger simultaneity must obtain
    it from the participating authorities before constructing the cut.
    """

    cut_id: str
    branch_id: str
    anchors: tuple[ExecutionStateAnchor, ...]

    def __post_init__(self) -> None:
        _require_text("cut_id", self.cut_id)
        _require_text("branch_id", self.branch_id)
        if not isinstance(self.anchors, tuple) or not self.anchors:
            raise ValueError("execution lineage source cut requires state anchors")
        if any(not isinstance(anchor, ExecutionStateAnchor) for anchor in self.anchors):
            raise TypeError("execution lineage anchors must be ExecutionStateAnchor values")
        identities = tuple((anchor.authority, anchor.state_id) for anchor in self.anchors)
        if len(set(identities)) != len(identities):
            raise ValueError("execution lineage source cut contains duplicate state identity")
        object.__setattr__(
            self,
            "anchors",
            tuple(sorted(self.anchors, key=lambda anchor: (anchor.authority, anchor.state_id, anchor.sha256))),
        )

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": "execution-source-cut.v1",
                "cut_id": self.cut_id,
                "branch_id": self.branch_id,
                "anchors": [anchor.to_payload() for anchor in self.anchors],
            }
        )


@dataclass(frozen=True, slots=True)
class ExecutionForkReceipt:
    """Immutable lineage fact binding one child branch to an exact source cut.

    The receipt is intentionally policy-free: it says nothing about search
    strategy, branch value, reward, reflection, task success, or state
    equivalence after the fork. It only identifies the source cut and child
    lineage.
    """

    fork_id: str
    source_cut: ExecutionSourceCut
    child_branch_id: str

    def __post_init__(self) -> None:
        _require_text("fork_id", self.fork_id)
        if not isinstance(self.source_cut, ExecutionSourceCut):
            raise TypeError("execution lineage fork requires ExecutionSourceCut")
        _require_text("child_branch_id", self.child_branch_id)
        if self.child_branch_id == self.source_cut.branch_id:
            raise ValueError("execution lineage child branch must differ from parent branch")

    @property
    def parent_branch_id(self) -> str:
        return self.source_cut.branch_id

    @property
    def source_cut_id(self) -> str:
        return self.source_cut.cut_id

    @property
    def source_cut_digest(self) -> str:
        return self.source_cut.digest

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "schema_version": "execution-fork-receipt.v1",
                "fork_id": self.fork_id,
                "parent_branch_id": self.parent_branch_id,
                "child_branch_id": self.child_branch_id,
                "source_cut_id": self.source_cut_id,
                "source_cut_digest": self.source_cut_digest,
            }
        )


def bind_execution_fork(
    source_cut: ExecutionSourceCut,
    *,
    fork_id: str,
    child_branch_id: str,
) -> ExecutionForkReceipt:
    """Create a policy-neutral parent-to-child execution lineage receipt."""

    return ExecutionForkReceipt(
        fork_id=fork_id,
        source_cut=source_cut,
        child_branch_id=child_branch_id,
    )


__all__ = [
    "ExecutionForkReceipt",
    "ExecutionSourceCut",
    "ExecutionStateAnchor",
    "bind_execution_fork",
]
