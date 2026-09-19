from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import Condition, Lock
import time

from noetrium_platform.research.execution.admission.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionMode,
    AdmissionRejected,
    AdmissionTopologySnapshot,
    GroupAdmissionSnapshot,
    LaneAdmissionSnapshot,
    ResourceAdmissionSnapshot,
    TenantAdmissionSnapshot,
)
from noetrium_platform.research.execution.scheduling.api import AdmissionSchedulingPolicyPort, SchedulingCandidate
from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    TaskCancelled,
)


@dataclass(frozen=True, slots=True)
class _GroupIdentity:
    tenant_id: str | None
    resource_id: str | None

    @property
    def resource_key(self) -> tuple[str | None, str] | None:
        if self.resource_id is None:
            return None
        return (self.tenant_id, self.resource_id)


@dataclass(frozen=True, slots=True)
class _Waiter:
    ticket: int
    group_id: str
    lane_kind: ExecutionLaneKind
    intent: AdmissionIntent
    enqueued_monotonic: float


class _AdmissionLease:
    def __init__(self, authority: "HierarchicalAdmissionAuthority", group_id: str, lane_kind: ExecutionLaneKind) -> None:
        self._authority = authority
        self._group_id = group_id
        self._lane_kind = lane_kind
        self._released = False
        self._lock = Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._authority._release(self._group_id, self._lane_kind)


class HierarchicalAdmissionAuthority:
    """Owns hierarchical execution admission; delegates ordering to scheduling.

    This runtime owns capacity/accounting only. It does not define priority rank,
    aging, or group fairness; those decisions are supplied by execution/scheduling.
    """

    _POLL_SECONDS = 0.05

    def __init__(self, *, budget: AdmissionBudget, scheduling: AdmissionSchedulingPolicyPort) -> None:
        self._budget = budget
        self._scheduling = scheduling
        self._lane_limits = {
            lane: budget.lane_limit(lane)
            for lane in (
                ExecutionLaneKind.BLOCKING_IO,
                ExecutionLaneKind.ASYNC_IO,
                ExecutionLaneKind.CPU,
                ExecutionLaneKind.SERIAL,
            )
        }
        self._condition = Condition()
        self._in_flight = 0
        self._groups: dict[str, int] = {}
        self._tenants: dict[str, int] = {}
        self._resources: dict[tuple[str | None, str], int] = {}
        self._lanes: dict[ExecutionLaneKind, int] = {}
        self._group_identities: dict[str, _GroupIdentity] = {}
        self._group_intents: dict[str, AdmissionIntent] = {}
        self._waiters: dict[int, _Waiter] = {}
        self._queue_version = 0
        self._selection_cache_version = -1
        self._selection_cache_bucket = -1
        self._selection_cache_ticket: int | None = None
        self._next_ticket = 0
        self._grant_sequence = 0
        self._group_last_grant: dict[str, int] = {}
        self._closed = False
        self._admitted_total = 0
        self._rejected_total = 0
        self._cancelled_total = 0
        self._timed_out_total = 0
        self._queued_total = 0
        self._cumulative_queue_wait_seconds = 0.0
        self._max_queue_wait_seconds = 0.0

    @staticmethod
    def _group_id(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("admission group id must be text")
        resolved = value.strip()
        if not resolved:
            raise ValueError("admission group id required")
        return resolved

    def register_group(self, group_id: str, *, identity: AdmissionIdentity, intent: AdmissionIntent = AdmissionIntent()) -> None:
        if not isinstance(identity, AdmissionIdentity):
            raise TypeError("admission identity must be AdmissionIdentity")
        if not isinstance(intent, AdmissionIntent):
            raise TypeError("admission intent must be AdmissionIntent")
        resolved_group = self._group_id(group_id)
        if not resolved_group:
            raise ValueError("admission group id required")
        resolved_identity = _GroupIdentity(
            tenant_id=identity.tenant_id,
            resource_id=identity.resource_id,
        )
        with self._condition:
            if self._closed:
                raise RuntimeError("execution admission authority is closed")
            if resolved_group in self._group_identities:
                raise ValueError(f"admission group id already registered: {resolved_group}")
            self._group_identities[resolved_group] = resolved_identity
            self._group_intents[resolved_group] = intent

    def unregister_group(self, group_id: str) -> None:
        resolved_group = self._group_id(group_id)
        with self._condition:
            self._identity(resolved_group)
            if self._groups.get(resolved_group, 0) != 0:
                raise RuntimeError(
                    f"cannot unregister admission group with active permits: {resolved_group}"
                )
            if any(item.group_id == resolved_group for item in self._waiters.values()):
                raise RuntimeError(
                    f"cannot unregister admission group with queued waiters: {resolved_group}"
                )
            self._group_identities.pop(resolved_group, None)
            self._group_intents.pop(resolved_group, None)
            self._group_last_grant.pop(resolved_group, None)
            self._invalidate_selection()
            self._condition.notify_all()

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    def _identity(self, group_id: str) -> _GroupIdentity:
        identity = self._group_identities.get(group_id)
        if identity is None:
            raise KeyError(f"execution group is not registered with admission authority: {group_id}")
        return identity

    def _can_admit(self, group_id: str, lane_kind: ExecutionLaneKind) -> bool:
        identity = self._identity(group_id)
        if self._in_flight >= self._budget.max_total_in_flight:
            return False
        if self._groups.get(group_id, 0) >= int(self._budget.max_in_flight_per_group):
            return False
        if self._lanes.get(lane_kind, 0) >= self._lane_limits[lane_kind]:
            return False
        if identity.tenant_id is not None and self._tenants.get(identity.tenant_id, 0) >= int(self._budget.max_in_flight_per_tenant):
            return False
        resource_key = identity.resource_key
        if resource_key is not None and self._resources.get(resource_key, 0) >= int(self._budget.max_in_flight_per_resource):
            return False
        return True

    def _invalidate_selection(self) -> None:
        self._queue_version += 1
        self._selection_cache_ticket = None

    def _selected_waiter(self) -> _Waiter | None:
        now = time.monotonic()
        bucket = int(now / self._POLL_SECONDS)
        if self._selection_cache_version == self._queue_version and self._selection_cache_bucket == bucket:
            if self._selection_cache_ticket is None:
                return None
            return self._waiters.get(self._selection_cache_ticket)
        selected: _Waiter | None = None
        if self._in_flight < self._budget.max_total_in_flight:
            candidates = tuple(
                item for item in self._waiters.values()
                if self._can_admit(item.group_id, item.lane_kind)
            )
            if candidates:
                candidate_rows = tuple(
                    SchedulingCandidate(
                        ticket=item.ticket,
                        group_id=item.group_id,
                        priority=item.intent.priority,
                        enqueued_monotonic=item.enqueued_monotonic,
                    )
                    for item in candidates
                )
                ticket = self._scheduling.select(
                    candidate_rows,
                    group_last_grant=dict(self._group_last_grant),
                    now_monotonic=now,
                )
                selected = self._waiters.get(ticket)
                if selected is None:
                    raise RuntimeError("scheduling policy selected an unknown admission ticket")
        self._selection_cache_version = self._queue_version
        self._selection_cache_bucket = bucket
        self._selection_cache_ticket = None if selected is None else selected.ticket
        return selected

    def _grant(self, group_id: str, lane_kind: ExecutionLaneKind, *, waited_seconds: float) -> _AdmissionLease:
        if not self._can_admit(group_id, lane_kind):
            raise RuntimeError("admission grant violated configured budget")
        identity = self._identity(group_id)
        self._in_flight += 1
        self._groups[group_id] = self._groups.get(group_id, 0) + 1
        self._lanes[lane_kind] = self._lanes.get(lane_kind, 0) + 1
        if identity.tenant_id is not None:
            self._tenants[identity.tenant_id] = self._tenants.get(identity.tenant_id, 0) + 1
        resource_key = identity.resource_key
        if resource_key is not None:
            self._resources[resource_key] = self._resources.get(resource_key, 0) + 1
        self._grant_sequence += 1
        self._group_last_grant[group_id] = self._grant_sequence
        self._invalidate_selection()
        self._admitted_total += 1
        self._cumulative_queue_wait_seconds += waited_seconds
        self._max_queue_wait_seconds = max(self._max_queue_wait_seconds, waited_seconds)
        return _AdmissionLease(self, group_id, lane_kind)

    def acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> _AdmissionLease:
        group_id = self._group_id(group_id)
        if lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer scheduler does not consume execution admission")
        if lane_kind not in self._lane_limits:
            raise ValueError(f"unsupported admission lane: {lane_kind}")
        with self._condition:
            self._identity(group_id)
            if self._closed:
                raise RuntimeError("execution admission authority is closed")
            if self._cancelled(cancellation):
                self._cancelled_total += 1
                raise TaskCancelled(cancellation.reason or "execution admission cancelled")
            if deadline is not None and deadline.expired:
                self._timed_out_total += 1
                raise TimeoutError("execution admission deadline expired")

            if self._group_intents[group_id].mode is AdmissionMode.REJECT:
                if self._can_admit(group_id, lane_kind) and self._selected_waiter() is None:
                    return self._grant(group_id, lane_kind, waited_seconds=0.0)
                self._rejected_total += 1
                raise AdmissionRejected(
                    f"execution admission rejected group={group_id} lane={lane_kind.value}"
                )

            waiter = _Waiter(
                ticket=self._next_ticket,
                group_id=group_id,
                lane_kind=lane_kind,
                intent=self._group_intents[group_id],
                enqueued_monotonic=time.monotonic(),
            )
            self._next_ticket += 1
            self._waiters[waiter.ticket] = waiter
            self._invalidate_selection()
            self._queued_total += 1
            try:
                while True:
                    if self._closed:
                        raise RuntimeError("execution admission authority is closed")
                    if self._cancelled(cancellation):
                        self._cancelled_total += 1
                        raise TaskCancelled(cancellation.reason or "execution admission cancelled")
                    if deadline is not None and deadline.expired:
                        self._timed_out_total += 1
                        raise TimeoutError("execution admission deadline expired")
                    if self._selected_waiter() is waiter:
                        self._waiters.pop(waiter.ticket, None)
                        self._invalidate_selection()
                        waited = max(0.0, time.monotonic() - waiter.enqueued_monotonic)
                        lease = self._grant(group_id, lane_kind, waited_seconds=waited)
                        self._condition.notify_all()
                        return lease
                    remaining = None if deadline is None else deadline.remaining_seconds
                    wait_for = self._POLL_SECONDS if remaining is None else min(self._POLL_SECONDS, remaining)
                    self._condition.wait(wait_for)
            finally:
                if waiter.ticket in self._waiters:
                    self._waiters.pop(waiter.ticket, None)
                    self._invalidate_selection()
                    self._condition.notify_all()

    @staticmethod
    def _decrement(counter: dict, key: object, *, label: str) -> None:
        current = counter.get(key, 0)
        if current <= 0:
            raise RuntimeError(f"admission {label} accounting underflow")
        if current == 1:
            counter.pop(key, None)
        else:
            counter[key] = current - 1

    def _release(self, group_id: str, lane_kind: ExecutionLaneKind) -> None:
        with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("admission in-flight accounting underflow")
            identity = self._identity(group_id)
            self._decrement(self._groups, group_id, label="group")
            self._decrement(self._lanes, lane_kind, label="lane")
            if identity.tenant_id is not None:
                self._decrement(self._tenants, identity.tenant_id, label="tenant")
            if identity.resource_key is not None:
                self._decrement(self._resources, identity.resource_key, label="resource")
            self._in_flight -= 1
            self._invalidate_selection()
            self._condition.notify_all()

    def _waiting_counters(self):
        waiters = tuple(self._waiters.values())
        by_group = Counter(item.group_id for item in waiters)
        by_lane = Counter(item.lane_kind for item in waiters)
        by_tenant: Counter[str] = Counter()
        by_resource: Counter[tuple[str | None, str]] = Counter()
        for item in waiters:
            identity = self._identity(item.group_id)
            if identity.tenant_id is not None:
                by_tenant[identity.tenant_id] += 1
            if identity.resource_key is not None:
                by_resource[identity.resource_key] += 1
        return by_group, by_lane, by_tenant, by_resource

    def snapshot(self) -> AdmissionTopologySnapshot:
        with self._condition:
            by_group, by_lane, by_tenant, by_resource = self._waiting_counters()
            now = time.monotonic()
            oldest = max((now - item.enqueued_monotonic for item in self._waiters.values()), default=0.0)
            group_ids = sorted(set(self._group_identities) | set(self._groups) | set(by_group))
            tenant_ids = sorted(set(self._tenants) | set(by_tenant))
            resource_keys = sorted(set(self._resources) | set(by_resource), key=lambda item: ((item[0] or ""), item[1]))
            lane_kinds = (
                ExecutionLaneKind.BLOCKING_IO,
                ExecutionLaneKind.ASYNC_IO,
                ExecutionLaneKind.CPU,
                ExecutionLaneKind.SERIAL,
            )
            return AdmissionTopologySnapshot(
                max_total_in_flight=self._budget.max_total_in_flight,
                max_in_flight_per_group=int(self._budget.max_in_flight_per_group),
                max_in_flight_per_tenant=int(self._budget.max_in_flight_per_tenant),
                max_in_flight_per_resource=int(self._budget.max_in_flight_per_resource),
                in_flight=self._in_flight,
                waiting=len(self._waiters),
                closed=self._closed,
                admitted_total=self._admitted_total,
                rejected_total=self._rejected_total,
                cancelled_total=self._cancelled_total,
                timed_out_total=self._timed_out_total,
                queued_total=self._queued_total,
                cumulative_queue_wait_seconds=self._cumulative_queue_wait_seconds,
                max_queue_wait_seconds=self._max_queue_wait_seconds,
                oldest_wait_seconds=max(0.0, oldest),
                groups=tuple(
                    GroupAdmissionSnapshot(
                        group_id=group_id,
                        tenant_id=self._group_identities[group_id].tenant_id,
                        resource_id=self._group_identities[group_id].resource_id,
                        in_flight=self._groups.get(group_id, 0),
                        waiting=by_group.get(group_id, 0),
                    )
                    for group_id in group_ids
                ),
                tenants=tuple(
                    TenantAdmissionSnapshot(
                        tenant_id=tenant_id,
                        max_in_flight=int(self._budget.max_in_flight_per_tenant),
                        in_flight=self._tenants.get(tenant_id, 0),
                        waiting=by_tenant.get(tenant_id, 0),
                    )
                    for tenant_id in tenant_ids
                ),
                resources=tuple(
                    ResourceAdmissionSnapshot(
                        tenant_id=tenant_id,
                        resource_id=resource_id,
                        max_in_flight=int(self._budget.max_in_flight_per_resource),
                        in_flight=self._resources.get((tenant_id, resource_id), 0),
                        waiting=by_resource.get((tenant_id, resource_id), 0),
                    )
                    for tenant_id, resource_id in resource_keys
                ),
                lanes=tuple(
                    LaneAdmissionSnapshot(
                        lane_kind=lane,
                        max_in_flight=self._lane_limits[lane],
                        in_flight=self._lanes.get(lane, 0),
                        waiting=by_lane.get(lane, 0),
                    )
                    for lane in lane_kinds
                ),
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
