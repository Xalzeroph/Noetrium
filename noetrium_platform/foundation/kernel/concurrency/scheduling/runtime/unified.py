from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator, Mapping
import heapq
import math
from threading import Lock

from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    ExecutionPriority,
    SchedulingAuthorityPort,
    SchedulingCandidate,
)


class _PersistentStateIndex(Mapping[str, "_SchedulingEntityState"]):
    """Immutable-path hash trie: lock-free readers, bounded-copy registration.

    Every publication replaces only one hash-trie path. The Scheduling
    Authority remains the exclusive writer and sole owner of the mutable
    states; the trie is just an immutable lookup projection.
    """

    __slots__ = ("_root", "_size")
    _BITS = 6
    _MASK = (1 << _BITS) - 1
    _BUCKET = 8

    def __init__(self) -> None:
        self._root = None
        self._size = 0

    @staticmethod
    def _hash(key: str) -> int:
        return hash(key) & ((1 << 64) - 1)

    @classmethod
    def _insert(cls, node, key: str, state: _SchedulingEntityState, digest: int, shift: int):
        if node is None:
            return ((digest, key, state),)
        if isinstance(node, tuple):
            if len(node) < cls._BUCKET or shift >= 66:
                return (*node, (digest, key, state))
            branch: dict[int, object] = {}
            for old_digest, old_key, old_state in node:
                part = (old_digest >> shift) & cls._MASK
                branch[part] = cls._insert(
                    branch.get(part), old_key, old_state, old_digest, shift + cls._BITS
                )
            return cls._insert(branch, key, state, digest, shift)
        part = (digest >> shift) & cls._MASK
        result = dict(node)
        result[part] = cls._insert(
            node.get(part), key, state, digest, shift + cls._BITS
        )
        return result

    def publish(self, key: str, state: _SchedulingEntityState) -> None:
        # Invoked only under the Scheduling Authority registry writer lock.
        if self.get(key) is not None:
            raise RuntimeError("duplicate scheduling entity registration: " + key)
        self._root = self._insert(self._root, key, state, self._hash(key), 0)
        self._size += 1

    def get(self, key: str, default=None):
        if type(key) is not str:
            return default
        digest = self._hash(key)
        node = self._root
        shift = 0
        while isinstance(node, dict):
            node = node.get((digest >> shift) & self._MASK)
            shift += self._BITS
        if node is not None:
            for old_digest, old_key, old_state in node:
                if old_digest == digest and old_key == key:
                    return old_state
        return default

    def __getitem__(self, key: str) -> _SchedulingEntityState:
        state = self.get(key)
        if state is None:
            raise KeyError(key)
        return state

    def __len__(self) -> int:
        return self._size

    def __iter__(self) -> Iterator[str]:
        stack = [self._root]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                stack.extend(node.values())
            elif node is not None:
                for _, key, _ in node:
                    yield key


class _SiblingServiceFrontier:
    """Incremental exact sibling service floor, with no second scheduling truth.

    Heaps only index projections of the state owned by this Authority. Entries
    carry revisions so updates need no global scan, and stale tuples are
    amortized away. A frontier covers exactly one (entity kind, parent).
    """

    __slots__ = ("lock", "_states", "_active", "_completed")

    def __init__(self) -> None:
        self.lock = Lock()
        self._states: dict[int, tuple[_SchedulingEntityState, int]] = {}
        self._active: list[tuple[int, int, int]] = []
        self._completed: list[tuple[int, int, int]] = []

    def publish(self, state: _SchedulingEntityState) -> None:
        key = id(state)
        with self.lock:
            prior = self._states.get(key)
            revision = 1 if prior is None else prior[1] + 1
            self._states[key] = (state, revision)
            if state.in_flight > 0:
                heapq.heappush(
                    self._active,
                    (state.service_quanta + state.reserved_service_quanta, revision, key),
                )
            if state.last_completion >= 0:
                heapq.heappush(
                    self._completed,
                    (-state.last_completion, revision, key),
                )
            self._compact_if_needed()

    def _compact_if_needed(self) -> None:
        bound = max(64, 4 * len(self._states))
        if len(self._active) > bound:
            self._active = [
                (state.service_quanta + state.reserved_service_quanta, version, key)
                for key, (state, version) in self._states.items()
                if state.in_flight > 0
            ]
            heapq.heapify(self._active)
        if len(self._completed) > bound:
            self._completed = [
                (-state.last_completion, version, key)
                for key, (state, version) in self._states.items()
                if state.last_completion >= 0
            ]
            heapq.heapify(self._completed)

    def _first_other(
        self, heap: list[tuple[int, int, int]], *,
        exclude: _SchedulingEntityState,
        active: bool,
    ) -> tuple[int, int, int] | None:
        excluded: tuple[int, int, int] | None = None
        try:
            while heap:
                row = heap[0]
                entity, revision = self._states[row[2]]
                if revision != row[1] or (
                    (entity.in_flight > 0) if active
                    else (entity.last_completion >= 0)
                ) is False:
                    heapq.heappop(heap)
                    continue
                if entity is exclude:
                    excluded = heapq.heappop(heap)
                    continue
                return row
            return None
        finally:
            if excluded is not None:
                heapq.heappush(heap, excluded)

    def floor(self, *, exclude: _SchedulingEntityState) -> int:
        with self.lock:
            active = self._first_other(self._active, exclude=exclude, active=True)
            if active is not None:
                return active[0]
            completed = self._first_other(
                self._completed, exclude=exclude, active=False
            )
            if completed is None:
                return 0
            state, _version = self._states[completed[2]]
            return state.service_quanta + state.reserved_service_quanta


class _SchedulingEntityState:
    __slots__ = (
        "lock",
        "in_flight",
        "service_quanta",
        "reserved_service_quanta",
        "last_grant",
        "last_completion",
        "parent",
        "retire_requested",
        "frontier",
    )

    def __init__(self, *, parent: tuple[str, ...]) -> None:
        self.lock = Lock()
        self.in_flight = 0
        self.service_quanta = 0
        self.reserved_service_quanta = 0
        self.last_grant = -1
        self.last_completion = -1
        self.parent = parent
        self.retire_requested = False
        self.frontier: _SiblingServiceFrontier | None = None


class UnifiedSchedulingAuthority(SchedulingAuthorityPort):
    """Global online scheduling truth without global hot-path serialization.

    Physical feasibility remains in Admission/Resource/Provider authorities.
    This Authority owns one global ordering timeline plus tenant/resource/flow
    active service and dominant-service history.

    Registry updates are copy-on-write and rare (flow/resource/tenant lifecycle
    edges). Hot-path accounting locks only the exact tenant/resource/flow entities touched by an
    operation. Therefore unrelated flows scale independently; serialization is
    paid only where exact fair-share accounting mathematically requires it.
    """

    def __init__(self) -> None:
        self._rank = {
            ExecutionPriority.CRITICAL: 0,
            ExecutionPriority.HIGH: 1,
            ExecutionPriority.NORMAL: 2,
            ExecutionPriority.LOW: 3,
        }
        self._registry_lock = Lock()
        self._sequence_lock = Lock()
        self._grant_sequence = 0
        # Derived cache invalidation only; not an independent fairness ledger.
        self._ordering_generation = 0
        # A bounded disposable invalidation journal. If a consumer misses the
        # retained window it must rebuild from the same canonical VTC/LAS cut.
        self._ordering_changes: deque[tuple[int, str | None]] = deque(maxlen=4096)
        self._parent_frontiers: dict[
            tuple[str, tuple[str, ...]], _SiblingServiceFrontier
        ] = {}
        # Persistent radix roots are path-copied; readers take an immutable
        # structural snapshot without a registry lock or a full-dict copy.
        self._tenant_states = _PersistentStateIndex()
        self._resource_states = _PersistentStateIndex()
        self._flow_states = _PersistentStateIndex()

    @staticmethod
    def _identity(value: str, *, name: str) -> str:
        if type(value) is not str or not value.strip():
            raise ValueError(f"scheduling {name} must be non-empty text")
        return value.strip()

    @staticmethod
    def _permit_count(value: int) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError("scheduling permit_count must be positive")
        return value

    @staticmethod
    def _service_quanta(value: int) -> int:
        if type(value) is not int or value < 0:
            raise ValueError("scheduling service_quanta must be non-negative")
        return value

    def _entity(
        self,
        *,
        kind: str,
        key: str,
        parent: tuple[str, ...],
    ) -> _SchedulingEntityState:
        if kind == "tenant":
            mapping = self._tenant_states
        elif kind == "resource":
            mapping = self._resource_states
        elif kind == "flow":
            mapping = self._flow_states
        else:
            raise ValueError("unknown scheduling entity kind: " + kind)
        state = mapping.get(key)
        if state is not None:
            if state.parent != parent:
                raise RuntimeError(
                    "scheduling entity parent identity drift: "
                    f"kind={kind} key={key}"
                )
            return state
        with self._registry_lock:
            if kind == "tenant":
                mapping = self._tenant_states
            elif kind == "resource":
                mapping = self._resource_states
            else:
                mapping = self._flow_states
            state = mapping.get(key)
            if state is not None:
                if state.parent != parent:
                    raise RuntimeError(
                        "scheduling entity parent identity drift: "
                        f"kind={kind} key={key}"
                    )
                return state
            state = _SchedulingEntityState(parent=parent)
            sibling_key = (kind, parent)
            frontier = self._parent_frontiers.get(sibling_key)
            if frontier is None:
                frontier = _SiblingServiceFrontier()
                self._parent_frontiers[sibling_key] = frontier
            state.frontier = frontier
            frontier.publish(state)
            mapping.publish(key, state)
            return state

    @staticmethod
    def _resource_key(
        tenant_id: str | None,
        resource_id: str | None,
    ) -> str | None:
        if resource_id is None:
            return None
        # This is an identity, not a display label. Length prefixing keeps
        # arbitrary user-defined resource names injective even if a name
        # itself includes what used to be the ::resource:: separator.
        tenant = tenant_id or ""
        return f"{len(tenant)}:{tenant}{len(resource_id)}:{resource_id}"

    @staticmethod
    def _flow_key(
        tenant_id: str | None, resource_id: str | None, flow_id: str,
    ) -> str:
        """Globally unique flow coordinate, not a reused local task name.

        Every segment is length-prefixed, so delimiters inside user-defined
        identifiers cannot alias another tenant/resource/flow combination.
        The same coordinate names grant, completion, rollback and retirement.
        """
        parts = (tenant_id or "", resource_id or "", flow_id)
        return "".join(f"{len(part)}:{part}" for part in parts)

    @staticmethod
    def _lock_states(
        tenant_key: str | None,
        tenant_state: _SchedulingEntityState | None,
        resource_key: str | None,
        resource_state: _SchedulingEntityState | None,
        flow_key: str,
        flow_state: _SchedulingEntityState,
    ) -> tuple[_SchedulingEntityState, ...]:
        rows: list[tuple[str, str, _SchedulingEntityState]] = [
            ("flow", flow_key, flow_state)
        ]
        if resource_key is not None and resource_state is not None:
            rows.append(("resource", resource_key, resource_state))
        if tenant_key is not None and tenant_state is not None:
            rows.append(("tenant", tenant_key, tenant_state))
        rows.sort(key=lambda row: (row[0], row[1]))
        states = tuple(row[2] for row in rows)
        for state in states:
            state.lock.acquire()
        return states

    @staticmethod
    def _unlock_states(states: tuple[_SchedulingEntityState, ...]) -> None:
        for state in reversed(states):
            state.lock.release()

    @staticmethod
    def _publish_states(states: tuple[_SchedulingEntityState, ...]) -> None:
        for state in states:
            if state.frontier is None:
                raise RuntimeError("scheduling state lost its sibling index")
            state.frontier.publish(state)

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._grant_sequence += 1
            return self._grant_sequence

    def _record_ordering_change(self, flow_id: str | None) -> None:
        # Called only after all touched hierarchy entities have been updated.
        with self._sequence_lock:
            self._ordering_generation += 1
            self._ordering_changes.append(
                (self._ordering_generation, flow_id)
            )

    def record_grant(
        self,
        *,
        tenant_id: str | None,
        flow_id: str,
        resource_id: str | None = None,
        permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> int:
        flow = self._identity(flow_id, name="flow_id")
        count = self._permit_count(permit_count)
        reserved_service = self._service_quanta(reserved_service_quanta)
        tenant = (
            None
            if tenant_id is None
            else self._identity(tenant_id, name="tenant_id")
        )
        resource = (
            None
            if resource_id is None
            else self._identity(resource_id, name="resource_id")
        )
        resource_key = self._resource_key(tenant, resource)
        flow_key = self._flow_key(tenant, resource, flow)
        tenant_parent: tuple[str, ...] = ()
        resource_parent = (
            ()
            if tenant is None
            else ("tenant:" + tenant,)
        )
        flow_parent = (
            (*resource_parent, "resource:" + resource)
            if resource is not None
            else resource_parent
        )
        flow_state = self._entity(
            kind="flow",
            key=flow_key,
            parent=flow_parent,
        )
        resource_state = (
            None
            if resource_key is None
            else self._entity(
                kind="resource",
                key=resource_key,
                parent=resource_parent,
            )
        )
        tenant_state = (
            None
            if tenant is None
            else self._entity(
                kind="tenant",
                key=tenant,
                parent=tenant_parent,
            )
        )
        states = self._lock_states(
            tenant,
            tenant_state,
            resource_key,
            resource_state,
            flow_key,
            flow_state,
        )
        try:
            if flow_state.retire_requested and flow_state.in_flight != 0:
                raise RuntimeError(
                    "cannot grant a retiring scheduling flow: " + flow
                )
            # Sample the fairness frontier inside the same critical section
            # as reactivation and grant. Computing it before acquiring these
            # entity locks permits a concurrent completion to invalidate the
            # no-credit-accumulation floor before the grant linearizes.
            tenant_floor = (
                0 if tenant_state is None
                else tenant_state.frontier.floor(exclude=tenant_state)
            )
            resource_floor = (
                0 if resource_state is None
                else resource_state.frontier.floor(exclude=resource_state)
            )
            flow_floor = flow_state.frontier.floor(exclude=flow_state)
            if flow_state.in_flight == 0:
                flow_state.service_quanta = max(
                    flow_state.service_quanta,
                    flow_floor,
                )
                flow_state.retire_requested = False
            if resource_state is not None and resource_state.in_flight == 0:
                resource_state.service_quanta = max(
                    resource_state.service_quanta,
                    resource_floor,
                )
                resource_state.retire_requested = False
            if tenant_state is not None and tenant_state.in_flight == 0:
                tenant_state.service_quanta = max(
                    tenant_state.service_quanta,
                    tenant_floor,
                )
            sequence = self._next_sequence()
            flow_state.in_flight += count
            flow_state.reserved_service_quanta += reserved_service
            flow_state.last_grant = sequence
            if resource_state is not None:
                resource_state.in_flight += count
                resource_state.reserved_service_quanta += reserved_service
                resource_state.last_grant = sequence
            if tenant_state is not None:
                tenant_state.in_flight += count
                tenant_state.reserved_service_quanta += reserved_service
                tenant_state.last_grant = sequence
            self._record_ordering_change(flow)
            return sequence
        finally:
            try:
                self._publish_states(states)
            finally:
                self._unlock_states(states)

    def rollback_grant(
        self,
        *,
        tenant_id: str | None,
        flow_id: str,
        resource_id: str | None = None,
        permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> None:
        """Undo provisional accounting without manufacturing service history."""

        flow = self._identity(flow_id, name="flow_id")
        count = self._permit_count(permit_count)
        reserved_service = self._service_quanta(reserved_service_quanta)
        tenant = (
            None
            if tenant_id is None
            else self._identity(tenant_id, name="tenant_id")
        )
        resource = (
            None
            if resource_id is None
            else self._identity(resource_id, name="resource_id")
        )
        resource_key = self._resource_key(tenant, resource)
        flow_key = self._flow_key(tenant, resource, flow)
        flow_state = self._flow_states.get(flow_key)
        if flow_state is None:
            raise RuntimeError(
                "global scheduling rollback has no active flow: " + flow
            )
        resource_state = (
            None
            if resource_key is None
            else self._resource_states.get(resource_key)
        )
        if resource_key is not None and resource_state is None:
            raise RuntimeError(
                "global scheduling rollback has no active resource: "
                + str(resource)
            )
        tenant_state = (
            None if tenant is None else self._tenant_states.get(tenant)
        )
        if tenant is not None and tenant_state is None:
            raise RuntimeError(
                "global scheduling rollback has no active tenant: " + tenant
            )
        states = self._lock_states(
            tenant,
            tenant_state,
            resource_key,
            resource_state,
            flow_key,
            flow_state,
        )
        try:
            for label, state in (
                ("flow", flow_state),
                ("resource", resource_state),
                ("tenant", tenant_state),
            ):
                if state is None:
                    continue
                if state.in_flight < count:
                    raise RuntimeError(
                        f"global scheduling {label} rollback in-flight underflow"
                    )
                if state.reserved_service_quanta < reserved_service:
                    raise RuntimeError(
                        f"global scheduling {label} rollback service reservation underflow"
                    )
            # All hierarchy levels must validate before any authoritative
            # counter is modified; a corrupted parent must not leave a child
            # partially rolled back.
            for state in states:
                state.in_flight -= count
                state.reserved_service_quanta -= reserved_service
            self._record_ordering_change(flow)
        finally:
            try:
                self._publish_states(states)
            finally:
                self._unlock_states(states)

    def record_completion(
        self,
        *,
        tenant_id: str | None,
        flow_id: str,
        service_quanta: int,
        resource_id: str | None = None,
        permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> None:
        flow = self._identity(flow_id, name="flow_id")
        count = self._permit_count(permit_count)
        service = self._service_quanta(service_quanta)
        reserved_service = self._service_quanta(reserved_service_quanta)
        tenant = (
            None
            if tenant_id is None
            else self._identity(tenant_id, name="tenant_id")
        )
        resource = (
            None
            if resource_id is None
            else self._identity(resource_id, name="resource_id")
        )
        resource_key = self._resource_key(tenant, resource)
        flow_key = self._flow_key(tenant, resource, flow)
        flow_state = self._flow_states.get(flow_key)
        if flow_state is None:
            raise RuntimeError(
                "global scheduling completion has no active flow: " + flow
            )
        resource_state = (
            None
            if resource_key is None
            else self._resource_states.get(resource_key)
        )
        if resource_key is not None and resource_state is None:
            raise RuntimeError(
                "global scheduling completion has no active resource: "
                + str(resource)
            )
        tenant_state = (
            None if tenant is None else self._tenant_states.get(tenant)
        )
        if tenant is not None and tenant_state is None:
            raise RuntimeError(
                "global scheduling completion has no active tenant: " + tenant
            )
        states = self._lock_states(
            tenant,
            tenant_state,
            resource_key,
            resource_state,
            flow_key,
            flow_state,
        )
        retire = False
        try:
            for label, state in (
                ("flow", flow_state),
                ("resource", resource_state),
                ("tenant", tenant_state),
            ):
                if state is None:
                    continue
                if state.in_flight < count:
                    raise RuntimeError(
                        f"global scheduling {label} in-flight accounting underflow"
                    )
                if state.reserved_service_quanta < reserved_service:
                    raise RuntimeError(
                        f"global scheduling {label} service reservation underflow"
                    )
            # Authoritative flow/resource/tenant accounting is a single
            # transaction. None of the three levels may observe partial
            # completion if another level fails validation.
            completion_sequence = self._next_sequence()
            for state in states:
                state.in_flight -= count
                state.reserved_service_quanta -= reserved_service
                state.service_quanta += service
                state.last_completion = completion_sequence
            self._record_ordering_change(flow)
        finally:
            try:
                self._publish_states(states)
            finally:
                self._unlock_states(states)

    def release_flow(
        self, flow_id: str, *, tenant_id: str | None,
        resource_id: str | None = None,
    ) -> None:
        flow = self._identity(flow_id, name="flow_id")
        tenant = None if tenant_id is None else self._identity(tenant_id, name="tenant_id")
        resource = None if resource_id is None else self._identity(resource_id, name="resource_id")
        state = self._flow_states.get(self._flow_key(tenant, resource, flow))
        if state is None:
            return
        with state.lock:
            state.retire_requested = True
        self._record_ordering_change(flow)

    def release_resource(
        self,
        *,
        tenant_id: str | None,
        resource_id: str,
    ) -> None:
        tenant = (
            None
            if tenant_id is None
            else self._identity(tenant_id, name="tenant_id")
        )
        resource = self._identity(resource_id, name="resource_id")
        key = self._resource_key(tenant, resource)
        if key is None:
            return
        state = self._resource_states.get(key)
        if state is None:
            return
        with state.lock:
            # Resource accounting is shared across independently registered
            # groups and processes. A local group may retire while another
            # flow still owns grants. Record the retirement intent without
            # invalidating their permits; completion/rollback retains exact
            # accounting, and a later grant reactivates the idle resource.
            state.retire_requested = True
        self._record_ordering_change(None)

    @staticmethod
    def _state_snapshot(
        state: _SchedulingEntityState | None,
    ) -> tuple[int, int, int]:
        if state is None:
            return (0, 0, -1)
        with state.lock:
            return (
                state.in_flight,
                state.service_quanta + state.reserved_service_quanta,
                state.last_grant,
            )

    @staticmethod
    def _validated_now(now_monotonic: float) -> float:
        if isinstance(now_monotonic, bool) or not isinstance(
            now_monotonic, (int, float)
        ):
            raise TypeError("scheduling now_monotonic must be numeric")
        now = float(now_monotonic)
        if not math.isfinite(now) or now < 0:
            raise ValueError(
                "scheduling now_monotonic must be finite and non-negative"
            )
        return now

    def service_revision(self) -> int:
        """Process-local revision for exact cache invalidation."""
        with self._sequence_lock:
            return self._ordering_generation

    def service_changes_since(
        self, revision: int | None,
    ) -> tuple[int, frozenset[str] | None]:
        with self._sequence_lock:
            current = self._ordering_generation
            if revision == current:
                return current, frozenset()
            if revision is None or type(revision) is not int or revision > current:
                return current, None
            rows = tuple(
                (seq, flow)
                for seq, flow in self._ordering_changes
                if seq > revision
            )
            if len(rows) != current - revision or any(
                seq != revision + offset
                for offset, (seq, _flow) in enumerate(rows, 1)
            ):
                return current, None
            if any(flow is None for _seq, flow in rows):
                return current, None
            return current, frozenset(flow for _seq, flow in rows)

    def _ordering_key_from_snapshots(
        self,
        candidate: SchedulingCandidate,
        *,
        now: float,
        tenant_snapshot: tuple[int, int, int],
        resource_snapshot: tuple[int, int, int],
        flow_snapshot: tuple[int, int, int],
    ) -> tuple[int | float, ...]:
        (tenant_active, tenant_service, tenant_last_grant) = tenant_snapshot
        (resource_active, resource_service, resource_last_grant) = resource_snapshot
        (flow_active, flow_service, flow_last_grant) = flow_snapshot

        deadline = candidate.deadline_monotonic
        service_seconds = candidate.estimated_service_seconds
        # A deadline can only become a latest-start constraint when remaining
        # service is expressed in the same physical unit (seconds). Structural
        # cost, token count, or other domain-local scores must never be
        # subtracted from a monotonic clock.
        laxity = (
            math.inf
            if deadline is None or service_seconds is None
            else deadline - now - service_seconds
        )
        # An already-expired hard deadline cannot be rescued by dispatch.
        # Give it no urgency advantage over a still-feasible request; the
        # lifecycle owner performs the actual deadline rejection. A negative
        # laxity derived only from estimated service is not a *proof* of
        # infeasibility, so preserve best-effort urgency until real expiry.
        expired = deadline is not None and deadline <= now
        deadline_at_risk = (
            not expired and math.isfinite(laxity) and laxity <= 0.0
        )
        deadline_risk_rank = 2 if expired else (0 if deadline_at_risk else 1)
        # Estimated negative laxity does not entitle a task to unbounded
        # preference over a peer with an equally urgent live deadline.
        urgent_laxity = 0.0 if deadline_at_risk else math.inf
        deferred_deadline = math.inf if deadline is None else deadline
        service_rate = candidate.observed_service_rate_per_second
        exploration_rank = 0 if service_rate is None else 1
        maxweight_rank = (
            0.0
            if service_rate is None
            else -float(candidate.waiting_permits) * float(service_rate)
        )
        return (
            # Only a live, at-risk deadline crosses the fairness boundary.
            # An expired deadline cannot be made feasible by dispatch.
            deadline_risk_rank,
            urgent_laxity,
            # Hierarchical VTC/LAS service is the starvation-free entitlement.
            # Declared priority is intentionally below these terms, so an
            # unbounded high-priority arrival stream cannot starve a tenant,
            # resource, or flow that has received less service.
            tenant_service,
            tenant_active,
            tenant_last_grant,
            resource_service,
            resource_active,
            resource_last_grant,
            flow_service,
            flow_active,
            flow_last_grant,
            self._rank[candidate.priority],
            candidate.continuity_rank,
            candidate.speculation_rank,
            -candidate.critical_path_tail_work,
            candidate.expected_waste_cost,
            candidate.estimated_service_cost,
            exploration_rank,
            maxweight_rank,
            deferred_deadline,
            candidate.deterministic_tiebreak,
            candidate.ticket,
        )

    def ordering_key(
        self,
        candidate: SchedulingCandidate,
        *,
        now_monotonic: float,
    ) -> tuple[int | float, ...]:
        if not isinstance(candidate, SchedulingCandidate):
            raise TypeError(
                "scheduling candidates must be SchedulingCandidate values"
            )
        now = self._validated_now(now_monotonic)
        flow = candidate.flow_id or candidate.group_id
        flow_key = self._flow_key(
            candidate.tenant_id, candidate.resource_id, flow,
        )
        resource_key = self._resource_key(
            candidate.tenant_id,
            candidate.resource_id,
        )
        tenant_state = (
            None
            if candidate.tenant_id is None
            else self._tenant_states.get(candidate.tenant_id)
        )
        resource_state = (
            None
            if resource_key is None
            else self._resource_states.get(resource_key)
        )
        flow_state = self._flow_states.get(flow_key)
        (
            tenant_active,
            tenant_service,
            tenant_last_grant,
        ) = self._state_snapshot(tenant_state)
        (
            resource_active,
            resource_service,
            resource_last_grant,
        ) = self._state_snapshot(resource_state)
        (
            flow_active,
            flow_service,
            flow_last_grant,
        ) = self._state_snapshot(flow_state)

        deadline = candidate.deadline_monotonic
        service_seconds = candidate.estimated_service_seconds
        # A deadline can only become a latest-start constraint when remaining
        # service is expressed in the same physical unit (seconds). Structural
        # cost, token count, or other domain-local scores must never be
        # subtracted from a monotonic clock.
        laxity = (
            math.inf
            if deadline is None or service_seconds is None
            else deadline - now - service_seconds
        )
        # An already-expired hard deadline cannot be rescued by dispatch.
        # Give it no urgency advantage over a still-feasible request; the
        # lifecycle owner performs the actual deadline rejection. A negative
        # laxity derived only from estimated service is not a *proof* of
        # infeasibility, so preserve best-effort urgency until real expiry.
        expired = deadline is not None and deadline <= now
        deadline_at_risk = (
            not expired and math.isfinite(laxity) and laxity <= 0.0
        )
        deadline_risk_rank = 2 if expired else (0 if deadline_at_risk else 1)
        # Estimated negative laxity does not entitle a task to unbounded
        # preference over a peer with an equally urgent live deadline.
        urgent_laxity = 0.0 if deadline_at_risk else math.inf
        deferred_deadline = math.inf if deadline is None else deadline
        service_rate = candidate.observed_service_rate_per_second
        exploration_rank = 0 if service_rate is None else 1
        maxweight_rank = (
            0.0
            if service_rate is None
            else -float(candidate.waiting_permits) * float(service_rate)
        )
        return (
            # Only a live, at-risk deadline crosses the fairness boundary.
            # An expired deadline cannot be made feasible by dispatch.
            deadline_risk_rank,
            urgent_laxity,
            # Hierarchical VTC/LAS service is the starvation-free entitlement.
            # Declared priority is intentionally below these terms, so an
            # unbounded high-priority arrival stream cannot starve a tenant,
            # resource, or flow that has received less service.
            tenant_service,
            tenant_active,
            tenant_last_grant,
            resource_service,
            resource_active,
            resource_last_grant,
            flow_service,
            flow_active,
            flow_last_grant,
            self._rank[candidate.priority],
            candidate.continuity_rank,
            candidate.speculation_rank,
            -candidate.critical_path_tail_work,
            candidate.expected_waste_cost,
            candidate.estimated_service_cost,
            exploration_rank,
            maxweight_rank,
            deferred_deadline,
            candidate.deterministic_tiebreak,
            candidate.ticket,
        )

    def ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        """Project one coherent batch while snapshotting shared hierarchy once."""
        if type(candidates) is not tuple:
            raise TypeError("scheduling candidate batch must be a tuple")
        now = self._validated_now(now_monotonic)
        tenant_snapshots: dict[str | None, tuple[int, int, int]] = {}
        resource_snapshots: dict[tuple[str | None, str] | None, tuple[int, int, int]] = {}
        flow_snapshots: dict[tuple[str | None, str | None, str], tuple[int, int, int]] = {}
        projected = []
        for candidate in candidates:
            if not isinstance(candidate, SchedulingCandidate):
                raise TypeError(
                    "scheduling candidates must be SchedulingCandidate values"
                )
            tenant_key = candidate.tenant_id
            resource_key = self._resource_key(tenant_key, candidate.resource_id)
            flow = candidate.flow_id or candidate.group_id
            flow_key = self._flow_key(tenant_key, candidate.resource_id, flow)
            if tenant_key not in tenant_snapshots:
                tenant_snapshots[tenant_key] = self._state_snapshot(
                    None if tenant_key is None else self._tenant_states.get(tenant_key)
                )
            if resource_key not in resource_snapshots:
                resource_snapshots[resource_key] = self._state_snapshot(
                    None if resource_key is None else self._resource_states.get(resource_key)
                )
            if flow_key not in flow_snapshots:
                flow_snapshots[flow_key] = self._state_snapshot(
                    self._flow_states.get(flow_key)
                )
            projected.append(self._ordering_key_from_snapshots(
                candidate,
                now=now,
                tenant_snapshot=tenant_snapshots[tenant_key],
                resource_snapshot=resource_snapshots[resource_key],
                flow_snapshot=flow_snapshots[flow_key],
            ))
        return tuple(projected)

    def ordering_keys_at_revision(
        self, candidates: tuple[SchedulingCandidate, ...], *,
        now_monotonic: float, known_revision: int | None = None,
    ) -> tuple[int, tuple[tuple[int | float, ...], ...] | None]:
        """Fence process-local ranking against concurrent service transitions."""
        if known_revision is not None and (
            type(known_revision) is not int or known_revision < 0
        ):
            raise ValueError("scheduling revision must be non-negative integer")
        self._validated_now(now_monotonic)
        if type(candidates) is not tuple or any(
            not isinstance(candidate, SchedulingCandidate) for candidate in candidates
        ):
            raise TypeError("scheduling candidate batch must contain SchedulingCandidate values")
        while True:
            revision = self.service_revision()
            if revision == known_revision:
                return revision, None
            keys = self.ordering_keys(candidates, now_monotonic=now_monotonic)
            if self.service_revision() == revision:
                return revision, keys

    def ordering_projection_pairs(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[
        tuple[tuple[int | float, ...], tuple[int | float, ...]], ...
    ]:
        keys = self.ordering_keys(
            candidates, now_monotonic=now_monotonic,
        )
        # One canonical score and one read cut. All index partitions are
        # projections of this score, not independent ranking algorithms.
        return tuple(
            (key[:2] + key[11:], key[:2] + key[8:])
            for key in keys
        )

    def within_flow_ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        if candidates and any(
            (candidate.tenant_id, candidate.resource_id,
             candidate.flow_id or candidate.group_id)
            != (candidates[0].tenant_id, candidates[0].resource_id,
                candidates[0].flow_id or candidates[0].group_id)
            for candidate in candidates
        ):
            raise ValueError("within-flow ranking requires one flow identity")
        keys = self.ordering_keys(
            candidates, now_monotonic=now_monotonic,
        )
        # Key slots 2..10 are identical for the SAME flow. Factor them
        # out inside the authority rather than duplicating policy.
        return tuple(key[:2] + key[11:] for key in keys)

    def flow_relative_ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        """Factor the *identical* parent rank out of one-coordinate batches.

        The lexicographic VTC/LAS law is still the sole source of ordering.
        All candidates MUST share one (tenant, resource) coordinate; this
        reduction deletes only common tenant/resource terms. It is not a
        second scoring policy or approximation.
        """
        if any(
            (candidate.tenant_id, candidate.resource_id)
            != (candidates[0].tenant_id, candidates[0].resource_id)
            for candidate in candidates
        ):
            raise ValueError("relative ordering requires one tenant/resource cut")
        keys = self.ordering_keys(
            candidates, now_monotonic=now_monotonic,
        )
        return tuple(key[:2] + key[8:] for key in keys)

    def select(
        self,
        candidates: Iterable[SchedulingCandidate],
        *,
        now_monotonic: float,
    ) -> int:
        now = self._validated_now(now_monotonic)
        selected = min(
            candidates,
            key=lambda candidate: self.ordering_key(
                candidate,
                now_monotonic=now,
            ),
            default=None,
        )
        if selected is None:
            raise ValueError("scheduling candidates required")
        return selected.ticket

