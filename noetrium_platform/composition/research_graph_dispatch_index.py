"""Disposable Unit-ready dispatch projection over the ONE Scheduling Authority.

Dependency readiness belongs to the Unit frontier. Physical admissions belong
to the Resource/Execution Authority. This is merely a rebuildable index of
Scheduling Authority's actual ordering keys, never a separate fairness law.

Within the ResearchGraphScheduler all candidates share tenant/resource and
deadline. A flow's shared dynamic fairness prefix can therefore be rekeyed
once at its head, while the stable node-local suffix stays in its group heap.
A broken durable delta window rebuilds every live group rather than guessing.
"""
from __future__ import annotations

from heapq import heapify, heappop, heappush
from itertools import count
from typing import Callable

from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    SchedulingCandidate, SchedulingAuthorityPort,
)


class ResearchGraphDispatchIndex:
    def __init__(
        self,
        authority: SchedulingAuthorityPort,
        make_candidate: Callable[[str], SchedulingCandidate],
    ) -> None:
        self._authority = authority
        self._make = make_candidate
        self._nodes: dict[str, tuple[str, int]] = {}
        self._groups: dict[str, list[tuple[tuple, int, str]]] = {}
        self._heads: list[tuple[tuple, int, str, int]] = []
        self._epochs: dict[str, int] = {}
        self._revision: int | None = None
        self._sequence = count()
        self._coordinates: tuple[str | None, str | None] | None = None
        self._parked: dict[str, int | None] = {}
        self._retry_heap: list[tuple[int, str]] = []
        self._deadline_events: list[tuple[float, str, int]] = []
        self._deadline_queued: dict[str, float] = {}

    def _candidate(self, node_id: str) -> SchedulingCandidate:
        return self._make(node_id)

    @staticmethod
    def _next_deadline_transition(
        candidate: SchedulingCandidate, now: float,
    ) -> float | None:
        # The canonical VTC/LAS deadline rank changes at estimated
        # latest-start and then again when the *real* deadline expires.
        deadline = candidate.deadline_monotonic
        if deadline is None or deadline <= now:
            return None
        service = candidate.estimated_service_seconds
        if service is not None:
            latest_start = deadline - service
            if latest_start > now:
                return latest_start
        return deadline

    def next_rank_transition(self) -> float | None:
        while self._deadline_events:
            crossing, flow, generation = self._deadline_events[0]
            if (
                self._epochs.get(flow) == generation
                and self._deadline_queued.get(flow) == crossing
            ):
                return crossing
            heappop(self._deadline_events)
        return None

    def _compact_deadline_timers(self) -> None:
        # Service revisions may reschedule a flow's at-risk instant. Old
        # generation-tagged timers must remain bounded even for long papers.
        if len(self._deadline_events) <= max(64, 4 * len(self._groups)):
            return
        self._deadline_events = [
            (crossing, flow, generation)
            for crossing, flow, generation in self._deadline_events
            if (
                self._epochs.get(flow) == generation
                and self._deadline_queued.get(flow) == crossing
            )
        ]
        heapify(self._deadline_events)

    def _prune(self, flow: str) -> None:
        group = self._groups.get(flow)
        if group is None:
            return
        while group and group[0][2] not in self._nodes:
            heappop(group)
        if not group:
            del self._groups[flow]
            self._epochs.pop(flow, None)
            self._deadline_queued.pop(flow, None)

    def _refresh(self, flows: set[str], now: float) -> None:
        heads = []
        for flow in sorted(flows):
            self._prune(flow)
            group = self._groups.get(flow)
            if group:
                heads.append((flow, group[0]))
        if not heads:
            return
        candidates = tuple(self._candidate(entry[2]) for _, entry in heads)
        keys = self._authority.flow_relative_ordering_keys(
            candidates, now_monotonic=now,
        )
        if len(keys) != len(heads):
            raise RuntimeError("Scheduling Authority returned incomplete group ranking")
        for (flow, (_, insertion, _node_id)), key, candidate in zip(
            heads, keys, candidates, strict=True
        ):
            generation = self._epochs.get(flow, 0) + 1
            self._epochs[flow] = generation
            heappush(self._heads, (key, insertion, flow, generation))
            self._deadline_queued.pop(flow, None)
            crossing = self._next_deadline_transition(candidate, now)
            if crossing is not None:
                self._deadline_queued[flow] = crossing
                heappush(self._deadline_events, (crossing, flow, generation))
        if len(self._heads) > max(64, 4 * len(self._groups)):
            self._heads = [
                entry for entry in self._heads
                if self._epochs.get(entry[2]) == entry[3]
            ]
            heapify(self._heads)
        self._compact_deadline_timers()

    def _advance_authority(self, now: float) -> None:
        # A flow change is an exact invalidation only for the scheduler's
        # homogeneous tenant/resource projection. Otherwise fail-close to a
        # full rebuild of disposable ranking.
        for _ in range(16):
            revision, delta = self._authority.service_changes_since(self._revision)
            if delta is None:
                changed = set(self._groups)
            else:
                changed = set(delta) & self._groups.keys()
            while self._deadline_events and self._deadline_events[0][0] <= now:
                deadline, flow, generation = heappop(self._deadline_events)
                if (self._epochs.get(flow) == generation
                        and self._deadline_queued.get(flow) == deadline):
                    changed.add(flow)
            if changed:
                self._refresh(changed, now)
            self._revision = revision
            check, newer = self._authority.service_changes_since(revision)
            if check == revision:
                return
            # The next iteration merges a concurrent global grant/completion.
            # An event-gap forces a full group refresh, not stale scheduling.
            self._revision = revision
        raise RuntimeError("Scheduling Authority has no stable dispatch cut")

    def offer_many(self, node_ids, *, now: float) -> None:
        incoming = []
        for node_id in node_ids:
            if node_id in self._nodes or node_id in self._parked:
                continue
            candidate = self._candidate(node_id)
            flow = candidate.flow_id or candidate.group_id
            coordinate = (candidate.tenant_id, candidate.resource_id)
            if self._coordinates is None:
                self._coordinates = coordinate
            if coordinate != self._coordinates:
                raise RuntimeError(
                    "ResearchGraphDispatchIndex requires one tenant/resource cut"
                )
            position = next(self._sequence)
            self._nodes[node_id] = (flow, position)
            incoming.append((flow, position, node_id, candidate))
        if not incoming:
            return
        # Sample the cut *before* ranking so a concurrent grant between this
        # observation and the batch key read cannot be silently missed.
        # Bootstrapping the index must not require a second all-R rekey.
        if self._revision is None:
            self._revision = self._authority.service_changes_since(None)[0]
        # Materialize both local and global candidate keys from the SAME
        # Scheduling Authority cut. Cold graph admission is one O(R) batch
        # regardless of how many different paper flows are ready.
        projected = self._authority.ordering_projection_pairs(
            tuple(row[3] for row in incoming),
            now_monotonic=now,
        )
        if len(projected) != len(incoming):
            raise RuntimeError("Scheduling Authority truncated ready projections")
        by_flow: dict[str, list[tuple[str, int, tuple]]] = {}
        global_by_node_id: dict[str, tuple] = {}
        for (flow, sequence, node_id, _candidate), (local, global_key) in zip(
            incoming, projected, strict=True
        ):
            by_flow.setdefault(flow, []).append(
                (node_id, sequence, local)
            )
            global_by_node_id[node_id] = global_key
        affected = set(by_flow)
        cold_build = not self._groups
        for flow, entries in by_flow.items():
            group = self._groups.setdefault(flow, [])
            for node_id, sequence, key in entries:
                if cold_build:
                    group.append((key, sequence, node_id))
                else:
                    heappush(group, (key, sequence, node_id))
        if cold_build:
            for group in self._groups.values():
                heapify(group)
            self._heads.clear()
            self._deadline_events.clear()

        leaders = tuple(
            (flow, self._groups[flow][0])
            for flow in sorted(affected)
        )
        # During incremental admission an existing flow's head may not be
        # one of the new nodes. Query only such heads. All new heads reuse
        # their already-computed authoritative projection.
        missing_heads = tuple(
            leader[2] for _flow, leader in leaders
            if leader[2] not in global_by_node_id
        )
        missing_keys = self._authority.flow_relative_ordering_keys(
            tuple(self._candidate(node_id) for node_id in missing_heads),
            now_monotonic=now,
        ) if missing_heads else ()
        if len(missing_keys) != len(missing_heads):
            raise RuntimeError("Scheduling Authority truncated existing flow heads")
        global_by_node_id.update(zip(missing_heads, missing_keys, strict=True))
        head_keys = tuple(
            global_by_node_id[leader[2]]
            for _flow, leader in leaders
        )
        for (flow, (_local_key, leader_sequence, leader_id)), leader_key in zip(
            leaders, head_keys, strict=True
        ):
            generation = self._epochs.get(flow, 0) + 1
            self._epochs[flow] = generation
            if cold_build:
                self._heads.append(
                    (leader_key, leader_sequence, flow, generation)
                )
            else:
                heappush(
                    self._heads,
                    (leader_key, leader_sequence, flow, generation),
                )
            self._deadline_queued.pop(flow, None)
            candidate = self._candidate(leader_id)
            crossing = self._next_deadline_transition(candidate, now)
            if crossing is not None:
                self._deadline_queued[flow] = crossing
                if cold_build:
                    self._deadline_events.append(
                        (crossing, flow, generation)
                    )
                else:
                    heappush(
                        self._deadline_events,
                        (crossing, flow, generation),
                    )
        if cold_build:
            heapify(self._heads)
            heapify(self._deadline_events)
        if len(self._heads) > max(64, 4 * len(self._groups)):
            self._heads = [
                entry for entry in self._heads
                if self._epochs.get(entry[2]) == entry[3]
            ]
            heapify(self._heads)
        self._compact_deadline_timers()

    def take(self, limit: int, *, now: float) -> tuple[str, ...]:
        if type(limit) is not int or limit < 0:
            raise ValueError("dispatch window must be non-negative")
        if not limit or not self._groups:
            return ()
        self._advance_authority(now)
        taken: list[str] = []
        while len(taken) < limit and self._heads:
            key, sequence, flow, generation = heappop(self._heads)
            if self._epochs.get(flow) != generation:
                continue
            self._prune(flow)
            group = self._groups.get(flow)
            if not group:
                continue
            if group[0][1] != sequence:
                # A terminal/cancelled Unit was removed lazily since this
                # global head was installed. Its successor must compete with
                # all other flows under its OWN key; taking it immediately
                # would violate the single Scheduling Authority order.
                self._refresh({flow}, now)
                continue
            _, _, node_id = heappop(group)
            self._nodes.pop(node_id)
            taken.append(node_id)
            if group:
                self._refresh({flow}, now)
            else:
                self._groups.pop(flow, None)
                self._epochs.pop(flow, None)
                self._deadline_queued.pop(flow, None)
        return tuple(taken)

    def _prune_retry_head(self) -> None:
        while self._retry_heap:
            wake_at, node_id = self._retry_heap[0]
            if self._parked.get(node_id) == wake_at:
                return
            heappop(self._retry_heap)

    def _compact_retry_heap(self) -> None:
        if len(self._retry_heap) > max(64, 4 * len(self._parked)):
            self._retry_heap = [
                (wake_at, node_id)
                for wake_at, node_id in self._retry_heap
                if self._parked.get(node_id) == wake_at
            ]
            heapify(self._retry_heap)

    def park(self, node_id: str, *, retry_not_before_ns: int | None) -> None:
        if node_id in self._nodes:
            raise RuntimeError("parked Unit still indexed for dispatch")
        self._parked[node_id] = retry_not_before_ns
        if retry_not_before_ns is not None:
            heappush(self._retry_heap, (retry_not_before_ns, node_id))
        self._compact_retry_heap()

    def wake_due(self, *, now_ns: int) -> tuple[str, ...]:
        due: list[str] = []
        self._prune_retry_head()
        while self._retry_heap and self._retry_heap[0][0] <= now_ns:
            wake_at, node_id = heappop(self._retry_heap)
            if self._parked.get(node_id) == wake_at:
                self._parked.pop(node_id)
                due.append(node_id)
            self._prune_retry_head()
        return tuple(due)

    def release_parked(self, node_ids) -> tuple[str, ...]:
        ids = tuple(node_id for node_id in node_ids if node_id in self._parked)
        for node_id in ids:
            self._parked.pop(node_id)
        return ids

    def next_retry_ns(self) -> int | None:
        self._prune_retry_head()
        return self._retry_heap[0][0] if self._retry_heap else None

    @property
    def has_indexed(self) -> bool:
        return bool(self._nodes)

    @property
    def parked_ids(self) -> tuple[str, ...]:
        return tuple(self._parked)

    def forget(self, node_id: str) -> None:
        # Heap cells are tombstones, invalidated with an O(1) map delete.
        self._nodes.pop(node_id, None)
        self._parked.pop(node_id, None)

    def invalidate_flow(self, flow: str, *, now: float) -> None:
        # Local attempt evidence may affect risk and waste, beyond the
        # shared service counters. Rekey only the affected flow.
        self._prune(flow)
        group = self._groups.get(flow)
        if not group:
            return
        members = tuple(
            (sequence, node_id)
            for _key, sequence, node_id in group
            if node_id in self._nodes
        )
        if not members:
            return
        candidates = tuple(self._candidate(node_id) for _, node_id in members)
        keys = self._authority.within_flow_ordering_keys(
            candidates, now_monotonic=now,
        )
        self._groups[flow] = [
            (key, sequence, node_id)
            for (sequence, node_id), key in zip(members, keys, strict=True)
        ]
        heapify(self._groups[flow])
        self._refresh({flow}, now)
