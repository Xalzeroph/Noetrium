from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import require_sha256

from .contracts import ResearchGraphPlan


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be non-empty canonical text")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _optional_ns(value: object, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer nanosecond timestamp")
    return value


class ResearchGraphLiveNodeState(StrEnum):
    """Durable graph-level orchestration state.

    Domain execution truth remains in the lower Machine/Experiment authorities.
    RECONCILE_REQUIRED deliberately prevents blind replay when a process dies
    after lower execution may have started but before the graph can commit its
    terminal observation.
    """

    PENDING = "pending"
    READY = "ready"
    CLAIMED = "claimed"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    RECONCILE_REQUIRED = "reconcile_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ResearchGraphAttemptState(StrEnum):
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED_BEFORE_START = "expired_before_start"
    RECONCILE_REQUIRED = "reconcile_required"
    RECONCILED_SUCCEEDED = "reconciled_succeeded"
    RECONCILED_FAILED = "reconciled_failed"
    RECONCILED_RETRY = "reconciled_retry"


class ResearchGraphReconciliationDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ResearchGraphNodeExecutionRecord:
    execution_id: str
    node_id: str
    semantic_digest: str
    state: ResearchGraphLiveNodeState
    attempt_number: int = 0
    attempt_id: str | None = None
    lease_owner_id: str | None = None
    lease_expires_at_ns: int | None = None
    retry_not_before_ns: int | None = None
    failure_type: str | None = None
    failure_message: str | None = None
    blocked_by_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.execution_id, "research graph execution_id")
        _text(self.node_id, "research graph execution node_id")
        require_sha256(
            self.semantic_digest,
            "research graph execution node semantic_digest",
        )
        if not isinstance(self.state, ResearchGraphLiveNodeState):
            raise TypeError("research graph live node state must be typed")
        if type(self.attempt_number) is not int or self.attempt_number < 0:
            raise ValueError("research graph attempt_number must be non-negative")
        _optional_text(self.attempt_id, "research graph attempt_id")
        _optional_text(self.lease_owner_id, "research graph lease_owner_id")
        _optional_ns(
            self.lease_expires_at_ns,
            "research graph lease_expires_at_ns",
        )
        _optional_ns(
            self.retry_not_before_ns,
            "research graph retry_not_before_ns",
        )
        _optional_text(self.failure_type, "research graph failure_type")
        _optional_text(self.failure_message, "research graph failure_message")
        if type(self.blocked_by_node_ids) is not tuple:
            raise TypeError("research graph blocked_by_node_ids must be a tuple")
        blockers = tuple(
            sorted(
                _text(value, "research graph blocker node_id")
                for value in self.blocked_by_node_ids
            )
        )
        if len(blockers) != len(set(blockers)):
            raise ValueError("research graph blockers must be unique")
        object.__setattr__(self, "blocked_by_node_ids", blockers)

        active = {
            ResearchGraphLiveNodeState.CLAIMED,
            ResearchGraphLiveNodeState.RUNNING,
        }
        if self.state in active:
            if (
                self.attempt_number < 1
                or self.attempt_id is None
                or self.lease_owner_id is None
                or self.lease_expires_at_ns is None
            ):
                raise ValueError(
                    "active research graph nodes require attempt and lease identity"
                )
        if self.state is ResearchGraphLiveNodeState.RETRY_WAIT:
            if self.retry_not_before_ns is None:
                raise ValueError("retry-wait node requires retry_not_before_ns")
        if self.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
            if self.attempt_number < 1 or self.attempt_id is None:
                raise ValueError(
                    "reconciliation-required node requires uncertain attempt identity"
                )
        if self.state is ResearchGraphLiveNodeState.SUCCEEDED:
            if self.attempt_number < 1:
                raise ValueError("succeeded graph node requires an attempt")
        if self.state is ResearchGraphLiveNodeState.FAILED:
            if (
                self.attempt_number < 1
                or self.failure_type is None
                or self.failure_message is None
            ):
                raise ValueError(
                    "failed graph node requires attempt and failure metadata"
                )
        if self.state is ResearchGraphLiveNodeState.BLOCKED and not blockers:
            raise ValueError("blocked graph node requires blockers")
        if self.state is not ResearchGraphLiveNodeState.BLOCKED and blockers:
            raise ValueError("only blocked graph nodes may carry blockers")
        if self.state is not ResearchGraphLiveNodeState.FAILED and (
            self.failure_type is not None or self.failure_message is not None
        ):
            raise ValueError("only failed graph nodes may carry failure metadata")


@dataclass(frozen=True, slots=True)
class ResearchGraphAttemptRecord:
    execution_id: str
    node_id: str
    attempt_number: int
    attempt_id: str
    owner_id: str
    state: ResearchGraphAttemptState
    claimed_at_ns: int
    lease_expires_at_ns: int
    started_at_ns: int | None = None
    finished_at_ns: int | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        _text(self.execution_id, "research graph attempt execution_id")
        _text(self.node_id, "research graph attempt node_id")
        if type(self.attempt_number) is not int or self.attempt_number < 1:
            raise ValueError("research graph attempt_number must be positive")
        _text(self.attempt_id, "research graph attempt_id")
        _text(self.owner_id, "research graph attempt owner_id")
        if not isinstance(self.state, ResearchGraphAttemptState):
            raise TypeError("research graph attempt state must be typed")
        for field_name in (
            "claimed_at_ns",
            "lease_expires_at_ns",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        _optional_ns(self.started_at_ns, "research graph attempt started_at_ns")
        _optional_ns(self.finished_at_ns, "research graph attempt finished_at_ns")
        _optional_text(self.failure_type, "research graph attempt failure_type")
        _optional_text(self.failure_message, "research graph attempt failure_message")


@dataclass(frozen=True, slots=True)
class ResearchGraphExecutionSnapshot:
    execution_id: str
    graph_id: str
    graph_digest: str
    research_revision_digest: str
    generation: int
    nodes: tuple[ResearchGraphNodeExecutionRecord, ...]

    def __post_init__(self) -> None:
        _text(self.execution_id, "research graph snapshot execution_id")
        _text(self.graph_id, "research graph snapshot graph_id")
        require_sha256(self.graph_digest, "research graph snapshot graph_digest")
        require_sha256(
            self.research_revision_digest,
            "research graph snapshot research_revision_digest",
        )
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("research graph snapshot generation must be positive")
        if type(self.nodes) is not tuple or not self.nodes or any(
            type(node) is not ResearchGraphNodeExecutionRecord for node in self.nodes
        ):
            raise TypeError("research graph snapshot nodes must be a typed tuple")
        ordered = tuple(sorted(self.nodes, key=lambda node: node.node_id))
        ids = tuple(node.node_id for node in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("research graph snapshot node ids must be unique")
        if any(node.execution_id != self.execution_id for node in ordered):
            raise ValueError("research graph snapshot node execution identity drifted")
        object.__setattr__(self, "nodes", ordered)

    def node(self, node_id: str) -> ResearchGraphNodeExecutionRecord:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    @property
    def reconciliation_required_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if node.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
        )


class ResearchGraphExecutionConflict(RuntimeError):
    pass


class ResearchGraphExecutionNotFound(KeyError):
    pass


@runtime_checkable
class ResearchGraphExecutionStorePort(Protocol):
    """Graph-level attempt/lease authority, separate from lower scientific truth."""

    def ensure_execution(
        self,
        execution_id: str,
        plan: ResearchGraphPlan,
    ) -> ResearchGraphExecutionSnapshot: ...

    def snapshot(self, execution_id: str) -> ResearchGraphExecutionSnapshot: ...

    def mark_ready(
        self,
        execution_id: str,
        node_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def claim(
        self,
        execution_id: str,
        node_id: str,
        *,
        owner_id: str,
        now_ns: int,
        lease_expires_at_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def mark_running(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def renew_lease(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
        lease_expires_at_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def mark_succeeded(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def mark_failed(
        self,
        execution_id: str,
        node_id: str,
        *,
        attempt_id: str,
        owner_id: str,
        now_ns: int,
        failure_type: str,
        failure_message: str,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def mark_blocked(
        self,
        execution_id: str,
        node_id: str,
        *,
        blocked_by_node_ids: tuple[str, ...],
    ) -> ResearchGraphNodeExecutionRecord: ...

    def recover_expired(
        self,
        execution_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphExecutionSnapshot: ...

    def schedule_retry(
        self,
        execution_id: str,
        node_id: str,
        *,
        retry_not_before_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def resolve_reconciliation(
        self,
        execution_id: str,
        node_id: str,
        *,
        disposition: ResearchGraphReconciliationDisposition,
        now_ns: int,
        retry_not_before_ns: int | None = None,
        failure_type: str | None = None,
        failure_message: str | None = None,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def attempts(
        self,
        execution_id: str,
        node_id: str,
    ) -> tuple[ResearchGraphAttemptRecord, ...]: ...


__all__ = [
    "ResearchGraphAttemptRecord",
    "ResearchGraphAttemptState",
    "ResearchGraphExecutionConflict",
    "ResearchGraphExecutionNotFound",
    "ResearchGraphExecutionSnapshot",
    "ResearchGraphExecutionStorePort",
    "ResearchGraphLiveNodeState",
    "ResearchGraphNodeExecutionRecord",
    "ResearchGraphReconciliationDisposition",
]
