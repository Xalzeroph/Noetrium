from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from threading import Condition, Lock, get_ident
from typing import Protocol, runtime_checkable
import time
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    SingleFlightCache,
    TaskCancelled,
    wake_on_cancellation,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComplexityBound,
    ComplexityContract,
    blocking_wait,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.substrate.api import (
    ResourceCapacity,
    ResourceClaimConflict,
    ResourceAuthorityPort,
    claim_field,
    is_authority_lease,
    lease_field,
    resource_claim,
)

from ..api.admission import ModelAdmissionClosed, ModelAdmissionTimeout


class _ResourceCommitWakePort(Protocol):
    """Notifications are advisory; Resource Authority remains the sole truth."""

    def subscribe(
        self, resource_keys: frozenset[str], callback: Callable[[], None],
    ) -> Callable[[], None]: ...

    def close(self) -> None: ...


@runtime_checkable
class _ResourceKeyOrphanRecoveryPort(Protocol):
    """Optional precise crash-recovery projection for advisory denial paths."""

    def reconcile_orphan_claims_for_resource_keys(
        self, resource_keys: frozenset[str],
    ) -> tuple[NoetriumUnit, ...]: ...


@runtime_checkable
class _ResourceKeyExpiryWakePort(Protocol):
    """Optional lease-clock wake projection used only after capacity denial."""

    def next_claim_owner_expiry_delay_for_resource_keys(
        self, resource_keys: frozenset[str],
    ) -> float | None: ...


MODEL_ADMISSION_CAPACITY_SELECTION_COMPLEXITY = ComplexityContract(
    algorithm_id="model.admission.resource-authority.v1",
    implementation_digest=canonical_digest(
        (
            "model.admission.resource-authority.v1",
            "stable-generation",
            "capacity-dimension",
            "one-claim-per-request",
        )
    ),
    time_upper_bound=ComplexityBound.constant(),
    space_upper_bound=ComplexityBound.constant(),
    assumptions=(
        "global request order is owned by UnifiedSchedulingAuthority",
        "qualified model capacity is one Universal Resource Authority dimension",
        "cross-process contention is serialized by the Resource Authority writer",
    ),
    time_lower_bound=ComplexityBound.constant(),
    space_lower_bound=ComplexityBound.constant(),
)


@dataclass(frozen=True, slots=True)
class ModelAdmissionOwnerSnapshot:
    owner_id: str
    active: int
    waiting: int


@dataclass(frozen=True, slots=True)
class AdmissionSnapshot:
    capacity: int
    active: int
    waiting: int
    owners: tuple[ModelAdmissionOwnerSnapshot, ...] = ()


class AdmissionLease:
    """One affine Resource Authority claim for a model request."""

    def __init__(
        self,
        controller: "ModelAdmissionController",
        claim_id: str,
    ) -> None:
        self._controller = controller
        self._claim_id = claim_id
        self._released = False
        self._release_lock = Lock()

    @property
    def claim_id(self) -> str:
        """Opaque Resource Authority claim identifier for exact borrow authorization."""
        return self._claim_id

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._controller._release(self._claim_id)
            self._released = True

    def __enter__(self) -> "AdmissionLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.release()


class ModelAdmissionController:
    """Exact deployment-capacity projection over Universal Resource Authority.

    This object owns no independent capacity truth and no scheduling/fairness
    state. One exact deployment generation maps to one immutable Authority
    capacity dimension and one stable logical resource generation. Every active
    request is an affine claim of amount one on that dimension.

    The small local waiting projection exists for observability and same-process
    wake-up only. Cross-process safety and active capacity are entirely derived
    from Resource Authority claims.
    """

    _KIND = "model-admission-slot"
    _CROSS_PROCESS_RECHECK_SECONDS = 0.01
    # A sustained remote conflict does not justify 100 SQLite transactions/s
    # per waiter. Back off to at most 16 base intervals; local release,
    # cancellation and close continue to notify immediately.
    _CROSS_PROCESS_MAX_BACKOFF_EXPONENT = 4
    _ANONYMOUS_OWNER = "__anonymous__"

    def __init__(
        self,
        authority: ResourceAuthorityPort,
        owner_lease: NoetriumUnit,
        *,
        deployment_id: str,
        deployment_generation: str,
        qualified_capacity: int,
        change_feed: _ResourceCommitWakePort | None = None,
    ) -> None:
        if not isinstance(authority, ResourceAuthorityPort):
            raise TypeError(
                "model admission requires ResourceAuthorityPort backed by the single Resource Authority"
            )
        if not is_authority_lease(owner_lease):
            raise TypeError("model admission requires Authority owner lease")
        if bool(lease_field(owner_lease, "released")):
            raise ValueError("model admission owner lease is already released")
        if type(deployment_id) is not str or not deployment_id.strip():
            raise ValueError("model admission deployment_id is required")
        generation_text = str(deployment_generation).strip()
        if (
            len(generation_text) != 64
            or any(c not in "0123456789abcdef" for c in generation_text)
        ):
            raise ValueError(
                "model admission deployment_generation must be SHA-256"
            )
        if type(qualified_capacity) is not int or qualified_capacity <= 0:
            raise ValueError("qualified capacity must be positive")

        identity = canonical_digest(
            {
                "deployment_id": deployment_id.strip(),
                "deployment_generation": generation_text,
            }
        )
        self.capacity = qualified_capacity
        self._authority = authority
        self._change_feed = change_feed
        self._owner_lease = owner_lease
        self._owner_lease_id = str(lease_field(owner_lease, "lease_id"))
        self._deployment_id = deployment_id.strip()
        self._deployment_generation = generation_text
        self._dimension = "model-slot:" + identity
        self._resource_key = "model-admission:" + identity
        self._continuity_dimension = "model-continuity:v2:" + identity
        self._continuity_resource_key = "model-continuity:v2:" + identity
        self._continuity_capacity: int | None = None
        self._continuity_generation: int | None = None

        # Qualification capacity is part of the exact deployment generation.
        # First materializer declares it; all later materializers must prove the
        # same value rather than overwrite shared truth.
        self._authority.ensure_capacity(
            ResourceCapacity(((self._dimension, self.capacity),))
        )
        self._resource_generation = self._authority.ensure_generation(
            self._resource_key
        ).generation

        self._cv = Condition()
        self._waiting_by_owner: dict[str, int] = {}
        # Non-authoritative local wake hint: only successful physical releases
        # advance this epoch. Actual admission still requires a fresh Authority
        # transaction, including after an epoch change.
        self._local_release_epoch = 0
        self._committed_change_epoch = 0
        self._closing = False
        self._active_authorizations = 0
        self._authorization_threads: dict[int, int] = {}
        self._closed = False

    @property
    def contention_recheck_seconds(self) -> float:
        """Fallback only when no commit notification source is available."""
        return self._CROSS_PROCESS_RECHECK_SECONDS

    def subscribe_capacity_change(
        self, callback: Callable[[], None],
    ) -> Callable[[], None] | None:
        """Observe commits; each wake must recheck authoritative capacity."""
        if not callable(callback):
            raise TypeError("model capacity-change callback must be callable")
        feed = self._change_feed
        if feed is None:
            return None
        return feed.subscribe(
            frozenset((self._resource_key, self._continuity_resource_key)),
            callback,
        )

    def qualify_continuity(self, capacity: int) -> None:
        """Declare the measured per-deployment flow ceiling in Resource Authority.

        A slot reserved for an interactive lifetime consumes both the same
        physical model-slot dimension used by ordinary requests and the
        qualified continuity dimension. A second logical endpoint pool cannot
        promise the slot again, even in another process.
        """
        if type(capacity) is not int or not 0 < capacity <= self.capacity:
            raise ValueError("model continuity capacity must be qualified and within physical capacity")
        with self._cv:
            if self._closed or self._closing:
                raise ModelAdmissionClosed("cannot qualify closing model admission")
            if self._continuity_capacity is not None and self._continuity_capacity != capacity:
                raise ValueError("model continuity qualification drift for deployment generation")
            self._authority.ensure_capacity(
                ResourceCapacity(((self._continuity_dimension, capacity),))
            )
            self._continuity_generation = self._authority.ensure_generation(
                self._continuity_resource_key
            ).generation
            self._continuity_capacity = capacity

    def declare_continuity_claim(
        self,
        *,
        owner_id: str,
        flow_id: str,
    ) -> NoetriumUnit:
        """Atomically claim one proven physical continuity entitlement.

        This method never waits or performs global fairness selection. The
        caller's UnifiedSchedulingAuthority selects the eligible request;
        this Resource Authority alone determines physical claim feasibility.
        """
        owner = self._owner(owner_id)
        if type(flow_id) is not str or not flow_id.strip():
            raise ValueError("model continuity requires non-empty flow identity")
        flow = flow_id.strip()
        with self._cv:
            if self._closed or self._closing:
                raise ModelAdmissionClosed("model admission controller is closing")
            generation = self._continuity_generation
            if self._continuity_capacity is None or generation is None:
                raise RuntimeError("model continuity requires certified physical capacity")
        holder_key = self._continuity_resource_key + ":flow:" + uuid4().hex
        claim_id = "model-continuity:" + canonical_digest(
            {
                "resource_key": self._continuity_resource_key,
                "holder_key": holder_key,
                "owner_lease_id": self._owner_lease_id,
            }
        )
        claim = resource_claim(
            claim_id=claim_id,
            resource_key=self._continuity_resource_key,
            holder_key=holder_key,
            generation=generation,
            owner_scope=lease_field(self._owner_lease, "owner_scope"),
            scope_generation=int(lease_field(self._owner_lease, "scope_generation")),
            scope_lease_id=lease_field(self._owner_lease, "scope_lease_id"),
            owner_lease_id=self._owner_lease_id,
            amounts=((self._dimension, 1), (self._continuity_dimension, 1)),
            exclusive=(
                self._continuity_resource_key + ":flow:" + flow,
            ),
            attributes={
                "kind": "model-continuity-slot",
                "owner_id": owner,
                "flow_id": flow,
                "owner_lease_id": self._owner_lease_id,
                "deployment_id": self._deployment_id,
                "deployment_generation": self._deployment_generation,
            },
        )
        return claim

    def try_reserve_continuity(
        self, *, owner_id: str, flow_id: str,
    ) -> AdmissionLease | None:
        return self._try_authorize_claim(
            self.declare_continuity_claim(owner_id=owner_id, flow_id=flow_id)
        )

    @property
    def physical_continuity_capacity(self) -> int:
        if self._continuity_capacity is None:
            raise RuntimeError("physical model continuity not qualified")
        return self._continuity_capacity

    @property
    def physical_continuity_resource_key(self) -> str:
        return self._continuity_resource_key

    @property
    def physical_admission_resource_key(self) -> str:
        return self._resource_key

    def physical_bundle_snapshot(self, keys: frozenset[str]):
        return self._authority.snapshot_for_resource_keys(keys)

    def reconcile_physical_bundle_orphans(
        self, keys: frozenset[str],
    ) -> bool:
        """Recover dead model claims only after an advisory capacity denial."""
        if type(keys) is not frozenset or not keys:
            raise ValueError("model physical orphan recovery requires resource keys")
        authority = self._authority
        if not isinstance(authority, _ResourceKeyOrphanRecoveryPort):
            return False
        return bool(authority.reconcile_orphan_claims_for_resource_keys(keys))

    def physical_bundle_owner_expiry_recheck_seconds(
        self, keys: frozenset[str],
    ) -> float | None:
        """Return Authority-clock delay to the next relevant owner expiry."""
        if type(keys) is not frozenset or not keys:
            raise ValueError("model physical expiry recheck requires resource keys")
        authority = self._authority
        if not isinstance(authority, _ResourceKeyExpiryWakePort):
            return None
        return authority.next_claim_owner_expiry_delay_for_resource_keys(keys)

    def commit_continuity_bundle(
        self, claims: tuple[NoetriumUnit, ...],
    ) -> tuple[NoetriumUnit, ...]:
        return self._authority.admit_bundle(tuple((claim,) for claim in claims))

    def adopt_continuity_claim(self, claim: NoetriumUnit) -> AdmissionLease:
        if (
            str(claim_field(claim, "resource_key")) != self._continuity_resource_key
            or int(claim_field(claim, "generation")) != self._continuity_generation
        ):
            raise ModelAdmissionClosed("bundle continuity generation drift")
        attrs = dict(claim_field(claim, "attributes") or {})
        if (
            attrs.get("kind") != "model-continuity-slot"
            or attrs.get("owner_lease_id") != self._owner_lease_id
            or attrs.get("deployment_id") != self._deployment_id
            or attrs.get("deployment_generation") != self._deployment_generation
        ):
            raise ModelAdmissionClosed("bundle continuity ownership drift")
        with self._cv:
            if self._closing or self._closed:
                raise ModelAdmissionClosed("bundle controller is closing")
        return AdmissionLease(self, str(claim_field(claim, "claim_id")))

    def rollback_continuity_claim(self, claim: NoetriumUnit) -> None:
        self._release(str(claim_field(claim, "claim_id")))

    def _borrow_continuity(
        self,
        *,
        claim_id: str,
        owner_id: str,
        timeout_seconds: float | None,
        cancellation: CancellationTokenPort | None,
    ) -> AdmissionLease:
        """Borrow one already-authorized physical slot without double-counting it.

        An exclusive resource token serializes real requests on the reserved
        claim. This token is a Resource Authority fact, never a process-local
        semaphore that could admit twice across distinct logical pools.
        """
        if type(claim_id) is not str or not claim_id.strip():
            raise ValueError("model borrowed continuity requires a physical claim id")
        claim_id = claim_id.strip()
        owner = self._owner(owner_id)
        deadline = (
            None if timeout_seconds is None
            else time.monotonic() + float(timeout_seconds)
        )
        borrowed_claim = None
        consecutive_conflicts = 0
        cancellation_wake = ExitStack()
        cancellation_wake_installed = False
        change_wake_installed = False
        self._increment_waiting(owner)
        try:
            while True:
                with self._cv:
                    if self._closed or self._closing:
                        raise ModelAdmissionClosed("model admission controller is closing")
                    release_epoch = self._local_release_epoch
                    commit_epoch = self._committed_change_epoch
                if self._cancelled(cancellation):
                    raise TaskCancelled(self._cancel_reason(cancellation))
                matching = tuple(
                    claim for claim in self._claims_at_cut()[1]
                    if str(claim_field(claim, "claim_id")) == claim_id
                )
                if len(matching) != 1:
                    raise ModelAdmissionClosed("physical model continuity claim is not active")
                attrs = dict(claim_field(matching[0], "attributes") or {})
                if (
                    attrs.get("kind") != "model-continuity-slot"
                    or attrs.get("owner_id") != owner
                    or attrs.get("owner_lease_id") != self._owner_lease_id
                ):
                    raise ModelAdmissionClosed("physical continuity claim ownership drift")
                generation = self._continuity_generation
                if generation is None:
                    raise RuntimeError("continuity claim was never qualified")
                if borrowed_claim is None:
                    holder_key = self._continuity_resource_key + ":borrow:" + uuid4().hex
                    borrowed_claim = resource_claim(
                        claim_id="model-continuity-borrow:" + canonical_digest(
                            {"holder_key": holder_key, "claim_id": claim_id}
                        ),
                        resource_key=self._continuity_resource_key,
                        holder_key=holder_key,
                        generation=generation,
                        owner_scope=lease_field(self._owner_lease, "owner_scope"),
                        scope_generation=int(lease_field(self._owner_lease, "scope_generation")),
                        scope_lease_id=lease_field(self._owner_lease, "scope_lease_id"),
                        owner_lease_id=self._owner_lease_id,
                        exclusive=("active-model-continuity:" + claim_id,),
                        attributes={
                            "kind": "model-continuity-borrow",
                            "parent_claim_id": claim_id,
                            "owner_id": owner,
                            "owner_lease_id": self._owner_lease_id,
                        },
                    )
                # The shared handoff owns the entire authorization/rollback
                # lifetime, including shutdown and cancellation races.
                lease = self._try_authorize_claim(
                    borrowed_claim, cancellation=cancellation,
                )
                if lease is not None:
                    return lease
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise ModelAdmissionTimeout("model continuity physical borrow timed out")
                if cancellation is not None and not cancellation_wake_installed:
                    cancellation_wake.enter_context(
                        wake_on_cancellation(
                            cancellation,
                            self._cv,
                            notify_waiters=self._cv.notify_all,
                        )
                    )
                    cancellation_wake_installed = True
                if self._change_feed is not None and not change_wake_installed:
                    cancellation_wake.callback(
                        self._change_feed.subscribe(
                            frozenset((self._resource_key, self._continuity_resource_key)),
                            self._on_committed_resource_change,
                        )
                    )
                    change_wake_installed = True
                    # A commit could have occurred between the rejected claim
                    # and subscribing. Retry authorization once after the
                    # subscription handshake before sleeping indefinitely.
                    continue
                notified = self._await_authority_capacity_change(
                    cancellation=cancellation,
                    remaining=remaining,
                    consecutive_conflicts=consecutive_conflicts,
                    observed_release_epoch=release_epoch,
                    observed_commit_epoch=commit_epoch,
                )
                consecutive_conflicts = (
                    0 if notified else min(
                        consecutive_conflicts + 1,
                        self._CROSS_PROCESS_MAX_BACKOFF_EXPONENT,
                    )
                )
        finally:
            cancellation_wake.close()
            self._decrement_waiting(owner)

    def _await_authority_capacity_change(
        self,
        *,
        cancellation: CancellationTokenPort | None,
        remaining: float | None,
        consecutive_conflicts: int,
        observed_release_epoch: int,
        observed_commit_epoch: int,
    ) -> bool:
        """Sleep until an Authority event, local release or actual deadline.

        When an owned commit feed exists, it watches durable Resource Authority
        events; the waiter performs no timer-driven capacity probe. Without a
        commit feed, bounded re-observation is required for liveness because
        independent processes cannot otherwise signal this Condition.
        """
        if self._change_feed is None:
            scale = 1 << min(
                consecutive_conflicts, self._CROSS_PROCESS_MAX_BACKOFF_EXPONENT
            )
            fallback = self._CROSS_PROCESS_RECHECK_SECONDS * scale
            wait_for = fallback if remaining is None else min(fallback, remaining)
        else:
            wait_for = remaining
        wait_deadline = (
            None if wait_for is None else time.monotonic() + wait_for
        )
        with self._cv:
            while True:
                if self._closed or self._closing:
                    raise ModelAdmissionClosed("model admission controller is closing")
                if self._cancelled(cancellation):
                    raise TaskCancelled(self._cancel_reason(cancellation))
                if (
                    self._local_release_epoch != observed_release_epoch
                    or self._committed_change_epoch != observed_commit_epoch
                ):
                    return True
                if wait_deadline is None:
                    self._cv.wait()
                    continue
                remaining_wait = wait_deadline - time.monotonic()
                if remaining_wait <= 0:
                    return False
                self._cv.wait(remaining_wait)

    def _claims_at_cut(
        self,
    ) -> tuple[tuple[NoetriumUnit, ...], tuple[NoetriumUnit, ...]]:
        """One Authority observation cut for ordinary and continuity claims."""
        resource_keys = {self._resource_key}
        if self._continuity_generation is not None:
            resource_keys.add(self._continuity_resource_key)
        snapshot = self._authority.snapshot_for_resource_keys(frozenset(resource_keys))
        ordinary: list[NoetriumUnit] = []
        continuity: list[NoetriumUnit] = []
        for claim in snapshot.claims:
            key = str(claim_field(claim, "resource_key"))
            kind = dict(claim_field(claim, "attributes") or {}).get("kind")
            if key == self._resource_key:
                if kind != self._KIND:
                    raise RuntimeError("model admission resource contains foreign claim")
                ordinary.append(claim)
            elif key == self._continuity_resource_key:
                if kind not in {"model-continuity-slot", "model-continuity-borrow"}:
                    raise RuntimeError("model continuity resource contains foreign claim")
                continuity.append(claim)
            else:
                raise RuntimeError("model admission Authority snapshot crossed resource scope")
        return tuple(ordinary), tuple(continuity)

    @classmethod
    def _owner(cls, owner_id: str | None) -> str:
        if owner_id is None:
            return cls._ANONYMOUS_OWNER
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError(
                "model admission owner_id must be non-empty when provided"
            )
        return owner_id.strip()

    @staticmethod
    def _cancelled(
        cancellation: CancellationTokenPort | None,
    ) -> bool:
        return cancellation is not None and cancellation.cancelled

    @staticmethod
    def _cancel_reason(
        cancellation: CancellationTokenPort | None,
    ) -> str:
        return (
            cancellation.reason
            if cancellation is not None and cancellation.reason
            else "model admission cancelled"
        )

    def _claim(self, owner_id: str) -> NoetriumUnit:
        holder_key = (
            self._resource_key
            + ":request:"
            + uuid4().hex
        )
        claim_id = "model-admission:" + canonical_digest(
            {
                "resource_key": self._resource_key,
                "holder_key": holder_key,
                "owner_lease_id": self._owner_lease_id,
            }
        )
        return resource_claim(
            claim_id=claim_id,
            resource_key=self._resource_key,
            holder_key=holder_key,
            generation=self._resource_generation,
            owner_scope=lease_field(self._owner_lease, "owner_scope"),
            scope_generation=int(
                lease_field(self._owner_lease, "scope_generation")
            ),
            scope_lease_id=lease_field(
                self._owner_lease,
                "scope_lease_id",
            ),
            owner_lease_id=self._owner_lease_id,
            amounts=((self._dimension, 1),),
            attributes={
                "kind": self._KIND,
                "owner_id": owner_id,
                "owner_lease_id": self._owner_lease_id,
                "deployment_id": self._deployment_id,
                "deployment_generation": self._deployment_generation,
            },
        )

    def _try_authorize_claim(
        self,
        claim: NoetriumUnit,
        *,
        cancellation: CancellationTokenPort | None = None,
    ) -> AdmissionLease | None:
        """One handoff boundary for ordinary, reserved and borrowed claims.

        An in-flight Authority transaction is retained as owned work until its
        grant has been handed off or physically released. Controller close
        cannot report convergence while such work remains outstanding.
        """
        with self._cv:
            if self._closed or self._closing:
                raise ModelAdmissionClosed("model admission controller is closing")
            self._active_authorizations += 1
            thread_id = get_ident()
            self._authorization_threads[thread_id] = (
                self._authorization_threads.get(thread_id, 0) + 1
            )
        try:
            try:
                granted = self._authority.admit_bundle(((claim,),))[0]
            except ResourceClaimConflict:
                return None
            lease = AdmissionLease(self, str(claim_field(granted, "claim_id")))
            with self._cv:
                closing = self._closed or self._closing
                cancelled = self._cancelled(cancellation)
                if not (closing or cancelled):
                    return lease
            # Release outside _cv: physical Authority effects may block.
            lease.release()
            if closing:
                raise ModelAdmissionClosed(
                    "model admission controller closed during authorization"
                )
            raise TaskCancelled(self._cancel_reason(cancellation))
        finally:
            with self._cv:
                self._active_authorizations -= 1
                remaining = self._authorization_threads[thread_id] - 1
                if remaining:
                    self._authorization_threads[thread_id] = remaining
                else:
                    del self._authorization_threads[thread_id]
                self._cv.notify_all()

    def _increment_waiting(self, owner_id: str) -> None:
        with self._cv:
            if self._closed or self._closing:
                raise ModelAdmissionClosed(
                    "model admission controller is closing"
                )
            self._waiting_by_owner[owner_id] = (
                self._waiting_by_owner.get(owner_id, 0) + 1
            )

    def _decrement_waiting(self, owner_id: str) -> None:
        with self._cv:
            current = self._waiting_by_owner.get(owner_id, 0)
            if current <= 0:
                raise RuntimeError(
                    "model admission waiting accounting underflow"
                )
            if current == 1:
                self._waiting_by_owner.pop(owner_id, None)
            else:
                self._waiting_by_owner[owner_id] = current - 1
            self._cv.notify_all()

    def acquire(
        self,
        timeout_seconds: float | None = None,
        *,
        cancellation: CancellationTokenPort | None = None,
        owner_id: str | None = None,
        continuity_claim_id: str | None = None,
    ) -> AdmissionLease:
        if timeout_seconds is not None:
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or float(timeout_seconds) < 0
            ):
                raise ValueError(
                    "model admission timeout cannot be negative"
                )
        owner = self._owner(owner_id)
        if continuity_claim_id is not None:
            return self._borrow_continuity(
                claim_id=continuity_claim_id,
                owner_id=owner,
                timeout_seconds=timeout_seconds,
                cancellation=cancellation,
            )
        deadline = (
            None
            if timeout_seconds is None
            else time.monotonic() + float(timeout_seconds)
        )
        claim = self._claim(owner)
        consecutive_conflicts = 0
        cancellation_wake = ExitStack()
        cancellation_wake_installed = False
        change_wake_installed = False
        self._increment_waiting(owner)
        try:
            while True:
                with self._cv:
                    if self._closed or self._closing:
                        raise ModelAdmissionClosed(
                            "model admission controller is closing"
                        )
                    release_epoch = self._local_release_epoch
                    commit_epoch = self._committed_change_epoch
                if self._cancelled(cancellation):
                    raise TaskCancelled(self._cancel_reason(cancellation))

                lease = self._try_authorize_claim(
                    claim, cancellation=cancellation,
                )
                if lease is not None:
                    return lease

                remaining = (
                    None
                    if deadline is None
                    else deadline - time.monotonic()
                )
                if remaining is not None and remaining <= 0:
                    raise ModelAdmissionTimeout(
                        "model admission timed out at qualified Resource "
                        "Authority capacity"
                    )

                # Local releases notify immediately. Cross-process releases have
                # no process-local condition, so bounded re-observation is the
                # only waiting projection; safety remains Authority-owned.
                if cancellation is not None and not cancellation_wake_installed:
                    cancellation_wake.enter_context(
                        wake_on_cancellation(
                            cancellation,
                            self._cv,
                            notify_waiters=self._cv.notify_all,
                        )
                    )
                    cancellation_wake_installed = True
                if self._change_feed is not None and not change_wake_installed:
                    cancellation_wake.callback(
                        self._change_feed.subscribe(
                            frozenset((self._resource_key, self._continuity_resource_key)),
                            self._on_committed_resource_change,
                        )
                    )
                    change_wake_installed = True
                    # A commit could have occurred between the rejected claim
                    # and subscribing. Retry authorization once after the
                    # subscription handshake before sleeping indefinitely.
                    continue
                notified = self._await_authority_capacity_change(
                    cancellation=cancellation,
                    remaining=remaining,
                    consecutive_conflicts=consecutive_conflicts,
                    observed_release_epoch=release_epoch,
                    observed_commit_epoch=commit_epoch,
                )
                consecutive_conflicts = (
                    0 if notified else min(
                        consecutive_conflicts + 1,
                        self._CROSS_PROCESS_MAX_BACKOFF_EXPONENT,
                    )
                )
        finally:
            cancellation_wake.close()
            self._decrement_waiting(owner)

    def _on_committed_resource_change(self) -> None:
        with self._cv:
            self._committed_change_epoch += 1
            self._cv.notify_all()

    def _release(self, claim_id: str) -> None:
        self._authority.release_claim(claim_id)
        with self._cv:
            # Notification is not a grant: it only accelerates a fresh
            # Authority check after a locally observed physical release.
            self._local_release_epoch += 1
            self._cv.notify_all()

    def snapshot(self) -> AdmissionSnapshot:
        # An active request on a reserved continuity slot is recorded as a
        # zero-additional-capacity borrow on the same physical Authority. Count
        # the borrow as running service, but not the idle lifetime reservation.
        ordinary, continuity = self._claims_at_cut()
        continuity_borrows = tuple(
            row for row in continuity
            if dict(claim_field(row, "attributes") or {}).get("kind")
            == "model-continuity-borrow"
        )
        claims = (*ordinary, *continuity_borrows)
        active_by_owner: dict[str, int] = {}
        for claim in claims:
            attrs = dict(claim_field(claim, "attributes") or {})
            owner = str(attrs.get("owner_id") or "").strip()
            if not owner:
                raise RuntimeError(
                    "model admission claim lost owner identity"
                )
            active_by_owner[owner] = active_by_owner.get(owner, 0) + 1
        with self._cv:
            waiting_by_owner = dict(self._waiting_by_owner)
        owners = tuple(
            sorted(set(active_by_owner) | set(waiting_by_owner))
        )
        return AdmissionSnapshot(
            capacity=self.capacity,
            active=len(claims),
            waiting=sum(waiting_by_owner.values()),
            owners=tuple(
                ModelAdmissionOwnerSnapshot(
                    owner_id=owner,
                    active=active_by_owner.get(owner, 0),
                    waiting=waiting_by_owner.get(owner, 0),
                )
                for owner in owners
            ),
        )

    def close(self) -> None:
        # Reject new authorization transactions before checking a physical
        # empty cut. Wait for already-started grants to either hand off (close
        # then rejects active claims) or finish their Authority rollback.
        with self._cv:
            if self._authorization_threads.get(get_ident(), 0):
                raise RuntimeError(
                    "cannot close model admission reentrantly during Authority authorization"
                )
            while self._closing:
                self._cv.wait()
            if self._closed:
                return
            self._closing = True
            self._cv.notify_all()
            try:
                while self._active_authorizations:
                    self._cv.wait()
                ordinary, continuity = self._claims_at_cut()
                local_live = tuple(
                    claim
                    for claim in (*ordinary, *continuity)
                    if str(
                        dict(claim_field(claim, "attributes") or {}).get(
                            "owner_lease_id"
                        )
                        or ""
                    )
                    == self._owner_lease_id
                )
                if local_live:
                    raise RuntimeError(
                        "cannot close model admission while local Resource Authority "
                        f"claims remain: {len(local_live)}"
                    )
                self._closed = True
            finally:
                self._closing = False
                self._cv.notify_all()

    @property
    def closed(self) -> bool:
        with self._cv:
            return self._closed


class ModelAdmissionRegistry:
    """Exact deployment admission views over one Universal Resource Authority."""

    def __init__(
        self,
        authority: ResourceAuthorityPort,
        owner_lease: NoetriumUnit,
        *,
        change_feed: _ResourceCommitWakePort | None = None,
    ) -> None:
        if not isinstance(authority, ResourceAuthorityPort):
            raise TypeError(
                "model admission registry requires ResourceAuthorityPort backed by the single Resource Authority"
            )
        if not is_authority_lease(owner_lease):
            raise TypeError(
                "model admission registry requires Authority owner lease"
            )
        self._authority = authority
        self._owner_lease = owner_lease
        self._change_feed = change_feed
        self._lock = Lock()
        self._cv = Condition(self._lock)
        self._controllers: dict[
            tuple[str, str], ModelAdmissionController
        ] = {}
        self._creations: SingleFlightCache[ModelAdmissionController] = SingleFlightCache()
        self._active_lookups = 0
        self._closing = False
        self._closed = False

    def controller_for(
        self,
        *,
        deployment_id: str,
        deployment_generation: str,
        qualified_capacity: int,
        continuity_capacity: int | None = None,
    ) -> ModelAdmissionController:
        key = (deployment_id, deployment_generation)
        with self._cv:
            if self._closed or self._closing:
                raise ModelAdmissionClosed("model admission registry is closing")
            self._active_lookups += 1
        try:
            # Per-key single-flight preserves one controller identity while
            # allowing unrelated model deployments to qualify concurrently.
            # Only the Resource Authority decides durable physical capacity.
            controller = self._creations.get_or_create(
                canonical_digest(key),
                lambda: ModelAdmissionController(
                    self._authority,
                    self._owner_lease,
                    deployment_id=deployment_id,
                    deployment_generation=deployment_generation,
                    qualified_capacity=qualified_capacity,
                    change_feed=self._change_feed,
                ),
            )
            if controller.capacity != qualified_capacity:
                raise ValueError(
                    "qualified admission capacity drift for deployment generation"
                )
            if continuity_capacity is not None:
                controller.qualify_continuity(continuity_capacity)
            with self._cv:
                self._controllers[key] = controller
            return controller
        finally:
            with self._cv:
                self._active_lookups -= 1
                self._cv.notify_all()

    def close(self) -> None:
        with self._cv:
            while self._closing:
                self._cv.wait()
            if self._closed:
                return
            self._closing = True
            # Close cannot miss a model controller still being constructed
            # or qualified; all already-started lookups must publish or fail.
            while self._active_lookups:
                self._cv.wait()
            controllers = tuple(self._controllers.values())
        errors: list[BaseException] = []
        for controller in controllers:
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        if not errors and self._change_feed is not None:
            try:
                self._change_feed.close()
            except BaseException as exc:
                errors.append(exc)
        with self._cv:
            if not errors:
                self._closed = True
            self._closing = False
            self._cv.notify_all()
        if errors:
            raise BaseExceptionGroup(
                "model admission registry close failed",
                errors,
            )

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed


__all__ = [
    "AdmissionLease",
    "AdmissionSnapshot",
    "ModelAdmissionClosed",
    "ModelAdmissionController",
    "ModelAdmissionOwnerSnapshot",
    "ModelAdmissionRegistry",
    "ModelAdmissionTimeout",
    "MODEL_ADMISSION_CAPACITY_SELECTION_COMPLEXITY",
]
