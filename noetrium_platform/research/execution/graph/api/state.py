from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

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
    REUSED = "reused"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


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


class ResearchGraphNodeControlPhase(StrEnum):
    """Durable per-node admission/control intent inside one immutable graph cut."""

    ACTIVE = "active"
    DRAINING = "draining"
    PAUSED = "paused"
    RECOVERY_REQUIRED = "recovery_required"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ResearchGraphNodeControlRecord:
    execution_id: str
    node_id: str
    phase: ResearchGraphNodeControlPhase
    generation: int
    updated_at_ns: int

    def __post_init__(self) -> None:
        _text(self.execution_id, "research graph node control execution_id")
        _text(self.node_id, "research graph node control node_id")
        if not isinstance(self.phase, ResearchGraphNodeControlPhase):
            raise TypeError("research graph node control phase must be typed")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("research graph node control generation must be positive")
        _optional_ns(self.updated_at_ns, "research graph node control updated_at_ns")


class ResearchGraphControlPhase(StrEnum):
    """Durable orchestration control for one immutable ResearchGraph cut.

    This phase owns only graph admission/control intent. Lower Machine, Run,
    Effect, checkpoint and scientific truth remain in their canonical authorities.
    """

    ACTIVE = "active"
    DRAINING = "draining"
    PAUSED = "paused"
    RECOVERY_REQUIRED = "recovery_required"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ResearchGraphControlRecord:
    execution_id: str
    phase: ResearchGraphControlPhase
    generation: int
    updated_at_ns: int

    def __post_init__(self) -> None:
        _text(self.execution_id, "research graph control execution_id")
        if not isinstance(self.phase, ResearchGraphControlPhase):
            raise TypeError("research graph control phase must be typed")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("research graph control generation must be positive")
        _optional_ns(self.updated_at_ns, "research graph control updated_at_ns")


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
        if self.state is ResearchGraphLiveNodeState.REUSED:
            if (
                self.attempt_number != 0
                or self.attempt_id is not None
                or self.lease_owner_id is not None
                or self.lease_expires_at_ns is not None
            ):
                raise ValueError("reused graph node cannot fabricate an execution attempt")
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
        if self.state is ResearchGraphLiveNodeState.CANCELLED and (
            self.attempt_id is not None
            or self.lease_owner_id is not None
            or self.lease_expires_at_ns is not None
            or self.retry_not_before_ns is not None
        ):
            raise ValueError("cancelled graph node cannot retain active attempt state")
        if self.state is not ResearchGraphLiveNodeState.FAILED and (
            self.failure_type is not None or self.failure_message is not None
        ):
            raise ValueError("only failed graph nodes may carry failure metadata")

    @property
    def fencing_token(self) -> int:
        """Monotonic per-node fencing token for the current or last attempt."""
        return self.attempt_number


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

    @property
    def fencing_token(self) -> int:
        """Monotonic per-node token; stale attempts carry lower tokens."""
        return self.attempt_number


@dataclass(frozen=True, slots=True)
class ResearchGraphLeaseRenewal:
    node_id: str
    attempt_id: str
    owner_id: str
    lease_expires_at_ns: int

    def __post_init__(self) -> None:
        _text(self.node_id, "research graph lease renewal node_id")
        _text(self.attempt_id, "research graph lease renewal attempt_id")
        _text(self.owner_id, "research graph lease renewal owner_id")
        if type(self.lease_expires_at_ns) is not int or self.lease_expires_at_ns < 0:
            raise ValueError(
                "research graph lease renewal expiry must be a non-negative integer"
            )


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
        if type(node_id) is not str or not node_id:
            raise KeyError(node_id)
        index = bisect_left(
            self.nodes,
            node_id,
            key=lambda node: node.node_id,
        )
        if index >= len(self.nodes) or self.nodes[index].node_id != node_id:
            raise KeyError(node_id)
        return self.nodes[index]

    @property
    def reconciliation_required_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if node.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
        )


@dataclass(frozen=True, slots=True)
class ResearchGraphReuseRecord:
    execution_id: str
    node_id: str
    source_execution_id: str
    source_node_id: str
    semantic_digest: str
    proof_digest: str
    created_at_ns: int

    def __post_init__(self) -> None:
        _text(self.execution_id, "research graph reuse execution_id")
        _text(self.node_id, "research graph reuse node_id")
        _text(self.source_execution_id, "research graph reuse source_execution_id")
        _text(self.source_node_id, "research graph reuse source_node_id")
        if self.execution_id == self.source_execution_id:
            raise ValueError("research graph reuse must cross immutable execution cuts")
        require_sha256(self.semantic_digest, "research graph reuse semantic_digest")
        require_sha256(self.proof_digest, "research graph reuse proof_digest")
        _optional_ns(self.created_at_ns, "research graph reuse created_at_ns")


@dataclass(frozen=True, slots=True)
class ResearchGraphCutSwitchFence:
    """Exact source-cut transaction fence for an atomic active-ref switch."""

    source_execution_id: str
    active_cut_generation: int
    execution_generation: int
    graph_control: ResearchGraphControlRecord
    node_controls: tuple[ResearchGraphNodeControlRecord, ...]
    fence_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.source_execution_id, "research graph cut fence source_execution_id")
        if type(self.active_cut_generation) is not int or self.active_cut_generation < 1:
            raise ValueError(
                "research graph cut fence active_cut_generation must be positive"
            )
        if type(self.execution_generation) is not int or self.execution_generation < 1:
            raise ValueError(
                "research graph cut fence execution_generation must be positive"
            )
        if type(self.graph_control) is not ResearchGraphControlRecord:
            raise TypeError("research graph cut fence graph_control must be typed")
        if self.graph_control.execution_id != self.source_execution_id:
            raise ValueError("research graph cut fence graph control identity drifted")
        if type(self.node_controls) is not tuple or any(
            type(row) is not ResearchGraphNodeControlRecord
            for row in self.node_controls
        ):
            raise TypeError("research graph cut fence node_controls must be typed tuple")
        ordered = tuple(sorted(self.node_controls, key=lambda row: row.node_id))
        ids = tuple(row.node_id for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("research graph cut fence node controls must be unique")
        if any(row.execution_id != self.source_execution_id for row in ordered):
            raise ValueError("research graph cut fence node control identity drifted")
        object.__setattr__(self, "node_controls", ordered)
        object.__setattr__(
            self,
            "fence_digest",
            canonical_digest(
                {
                    "source_execution_id": self.source_execution_id,
                    "active_cut_generation": self.active_cut_generation,
                    "execution_generation": self.execution_generation,
                    "graph_control": (
                        self.graph_control.phase.value,
                        self.graph_control.generation,
                        self.graph_control.updated_at_ns,
                    ),
                    "node_controls": tuple(
                        (
                            row.node_id,
                            row.phase.value,
                            row.generation,
                            row.updated_at_ns,
                        )
                        for row in ordered
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchGraphActiveCutRef:
    logical_execution_id: str
    cut_id: str
    research_revision_digest: str
    graph_digest: str
    generation: int

    def __post_init__(self) -> None:
        _text(self.logical_execution_id, "research graph logical_execution_id")
        require_sha256(self.cut_id, "research graph active cut_id")
        require_sha256(
            self.research_revision_digest,
            "research graph active cut revision",
        )
        require_sha256(self.graph_digest, "research graph active cut graph_digest")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("research graph active cut generation must be positive")


@dataclass(frozen=True, slots=True)
class ResearchGraphActiveExecutionSnapshot:
    """One atomically observed logical-execution cut and its graph control truth."""

    active_cut: ResearchGraphActiveCutRef
    execution: ResearchGraphExecutionSnapshot
    control: ResearchGraphControlRecord

    def __post_init__(self) -> None:
        if type(self.active_cut) is not ResearchGraphActiveCutRef:
            raise TypeError("active execution snapshot active_cut must be typed")
        if type(self.execution) is not ResearchGraphExecutionSnapshot:
            raise TypeError("active execution snapshot execution must be typed")
        if type(self.control) is not ResearchGraphControlRecord:
            raise TypeError("active execution snapshot control must be typed")
        if self.active_cut.cut_id != self.execution.execution_id:
            raise ValueError("active execution snapshot cut identity drifted")
        if self.control.execution_id != self.execution.execution_id:
            raise ValueError("active execution snapshot control identity drifted")
        if self.active_cut.graph_digest != self.execution.graph_digest:
            raise ValueError("active execution snapshot graph digest drifted")
        if (
            self.active_cut.research_revision_digest
            != self.execution.research_revision_digest
        ):
            raise ValueError("active execution snapshot revision digest drifted")


class ResearchGraphReconciliationRequired(RuntimeError):
    def __init__(self, execution_id: str, node_ids: tuple[str, ...]) -> None:
        _text(execution_id, "research graph reconciliation execution_id")
        if type(node_ids) is not tuple or not node_ids or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in node_ids
        ):
            raise ValueError(
                "research graph reconciliation requires non-empty node ids"
            )
        ordered = tuple(sorted(node_ids))
        if len(ordered) != len(set(ordered)):
            raise ValueError("research graph reconciliation node ids must be unique")
        self.execution_id = execution_id
        self.node_ids = ordered
        super().__init__(
            "research graph execution requires reconciliation before dependent "
            f"work can continue: {execution_id} -> {ordered}"
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

    def node_state(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def node_states(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]: ...

    def mark_ready(
        self,
        execution_id: str,
        node_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def mark_ready_many(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
        *,
        now_ns: int,
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]: ...

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

    def renew_leases(
        self,
        execution_id: str,
        renewals: tuple[ResearchGraphLeaseRenewal, ...],
        *,
        now_ns: int,
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]: ...

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

    def mark_blocked_many(
        self,
        execution_id: str,
        transitions: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> tuple[ResearchGraphNodeExecutionRecord, ...]: ...

    def recover_expired(
        self,
        execution_id: str,
        *,
        now_ns: int,
    ) -> ResearchGraphExecutionSnapshot: ...

    def retry_failed_subgraph(
        self,
        execution_id: str,
        failed_node_id: str,
        *,
        descendant_node_ids: tuple[str, ...],
        retry_not_before_ns: int,
    ) -> ResearchGraphExecutionSnapshot: ...

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

    def mark_reused(
        self,
        execution_id: str,
        node_id: str,
        *,
        source_execution_id: str,
        source_node_id: str,
        semantic_digest: str,
        proof_digest: str,
        now_ns: int,
    ) -> ResearchGraphNodeExecutionRecord: ...

    def reuse_record(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphReuseRecord | None: ...

    def attempt_state(
        self,
        execution_id: str,
        node_id: str,
        attempt_number: int,
    ) -> ResearchGraphAttemptRecord: ...

    def attempts(
        self,
        execution_id: str,
        node_id: str,
    ) -> tuple[ResearchGraphAttemptRecord, ...]: ...


@runtime_checkable
class ResearchGraphControlStorePort(Protocol):
    """CAS-safe durable graph control authority.

    Control is scoped to one immutable physical execution cut. It never claims
    lower Machine/Run/effect state and cannot resolve reconciliation debt itself.
    """

    def control_state(
        self,
        execution_id: str,
    ) -> ResearchGraphControlRecord: ...

    def request_drain(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...

    def pause_if_quiescent(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...

    def resume(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...

    def interrupt(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...

    def cancel_if_quiescent(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...

    def require_recovery(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...

    def settle_recovery(
        self,
        execution_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphControlRecord: ...


@runtime_checkable
class ResearchGraphNodeControlStorePort(Protocol):
    """CAS-safe per-node control authority, independent of graph-wide control."""

    def node_control_state(
        self,
        execution_id: str,
        node_id: str,
    ) -> ResearchGraphNodeControlRecord: ...

    def node_control_snapshot(
        self,
        execution_id: str,
    ) -> tuple[ResearchGraphNodeControlRecord, ...]: ...

    def node_control_states(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
    ) -> tuple[ResearchGraphNodeControlRecord, ...]: ...

    def request_node_drain(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord: ...

    def pause_node_if_quiescent(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord: ...

    def resume_node(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord: ...

    def interrupt_node(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord: ...

    def settle_node_recovery(
        self,
        execution_id: str,
        node_id: str,
        *,
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord: ...

    def cancel_node_subgraph(
        self,
        execution_id: str,
        node_id: str,
        *,
        descendant_node_ids: tuple[str, ...],
        expected_generation: int,
        now_ns: int,
    ) -> ResearchGraphNodeControlRecord: ...


@runtime_checkable
class ResearchGraphActiveCutStorePort(Protocol):
    """CAS authority for the movable logical-execution -> immutable-cut ref."""

    def active_cut(
        self,
        logical_execution_id: str,
    ) -> ResearchGraphActiveCutRef | None: ...

    def active_execution_snapshot(
        self,
        logical_execution_id: str,
    ) -> ResearchGraphActiveExecutionSnapshot | None: ...

    def move_active_cut(
        self,
        logical_execution_id: str,
        cut_id: str,
        *,
        expected_cut_id: str | None = None,
        source_fence: ResearchGraphCutSwitchFence | None = None,
    ) -> ResearchGraphActiveCutRef: ...


__all__ = [
    "ResearchGraphActiveCutRef",
    "ResearchGraphActiveCutStorePort",
    "ResearchGraphActiveExecutionSnapshot",
    "ResearchGraphAttemptRecord",
    "ResearchGraphAttemptState",
    "ResearchGraphControlPhase",
    "ResearchGraphControlRecord",
    "ResearchGraphControlStorePort",
    "ResearchGraphCutSwitchFence",
    "ResearchGraphExecutionConflict",
    "ResearchGraphExecutionNotFound",
    "ResearchGraphExecutionSnapshot",
    "ResearchGraphExecutionStorePort",
    "ResearchGraphLeaseRenewal",
    "ResearchGraphLiveNodeState",
    "ResearchGraphNodeControlPhase",
    "ResearchGraphNodeControlRecord",
    "ResearchGraphNodeControlStorePort",
    "ResearchGraphNodeExecutionRecord",
    "ResearchGraphReconciliationDisposition",
    "ResearchGraphReconciliationRequired",
    "ResearchGraphReuseRecord",
]
