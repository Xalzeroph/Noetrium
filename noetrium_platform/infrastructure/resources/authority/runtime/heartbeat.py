from __future__ import annotations

from collections.abc import Callable
import hashlib
from threading import Lock
import time
from typing import Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskFailureScope,
    TaskGroupPort,
)

RowT = TypeVar("RowT")
PolicyT = TypeVar("PolicyT")


class LeaseHeartbeatError(RuntimeError):
    """A resource lease renewal loop lost authority or failed."""


class _LeaseHeartbeatBatchCoordinator(Generic[RowT]):
    """One renewal heartbeat for all live leases owned by one resource authority."""

    def __init__(
        self,
        *,
        renew: Callable[[tuple[RowT, ...]], tuple[RowT, ...]],
        row_identity: Callable[[RowT], str],
        row_expiry_epoch_s: Callable[[RowT], float | None] | None = None,
        heartbeat_namespace: str,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        interval_seconds: float,
        lane_capacity: int | None,
    ) -> None:
        if not heartbeat_namespace.strip() or not lane_id.strip():
            raise ValueError("lease heartbeat namespace and lane_id are required")
        if interval_seconds <= 0:
            raise ValueError("lease heartbeat interval must be positive")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError("lease heartbeat lane capacity must be positive")
        self._renew = renew
        self._row_identity = row_identity
        self._row_expiry_epoch_s = row_expiry_epoch_s
        self._heartbeat_namespace = heartbeat_namespace
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._interval_seconds = float(interval_seconds)
        self._lane_capacity = lane_capacity
        self._lock = Lock()
        self._next_member_id = 0
        self._rows_by_member: dict[int, tuple[RowT, ...]] = {}
        self._active_members: set[int] = set()
        self._identity_owner: dict[str, int] = {}
        self._member_failures: dict[int, BaseException] = {}
        self._scheduled: ScheduledTaskHandlePort | None = None
        self._closed = False

    def create_member(self, rows: tuple[RowT, ...]) -> int:
        if not rows:
            raise ValueError("lease heartbeat requires at least one row")
        identities = tuple(self._row_identity(row) for row in rows)
        if any(type(value) is not str or not value.strip() for value in identities):
            raise ValueError("lease heartbeat row identities must be non-empty text")
        if len(set(identities)) != len(identities):
            raise ValueError("lease heartbeat row identities must be unique")
        with self._lock:
            if self._closed:
                raise LeaseHeartbeatError("lease heartbeat coordinator is closed")
            self._next_member_id += 1
            member_id = self._next_member_id
            self._rows_by_member[member_id] = rows
            return member_id

    def rows(self, member_id: int) -> tuple[RowT, ...]:
        with self._lock:
            try:
                return self._rows_by_member[member_id]
            except KeyError as exc:
                raise LeaseHeartbeatError("lease heartbeat member is unknown") from exc

    def _heartbeat_id(self) -> str:
        return self._heartbeat_namespace + ":aggregate"

    def activate(self, member_id: int) -> None:
        with self._lock:
            if self._closed:
                raise LeaseHeartbeatError("lease heartbeat coordinator is closed")
            failure = self._member_failures.get(member_id)
            if failure is not None:
                raise LeaseHeartbeatError(
                    "lease heartbeat member previously lost renewal authority: "
                    f"{type(failure).__name__}: {failure}"
                ) from failure
            if member_id in self._active_members:
                return
            try:
                rows = self._rows_by_member[member_id]
            except KeyError as exc:
                raise LeaseHeartbeatError("lease heartbeat member is unknown") from exc
            identities = tuple(self._row_identity(row) for row in rows)
            conflicts = tuple(
                identity
                for identity in identities
                if identity in self._identity_owner
                and self._identity_owner[identity] != member_id
            )
            if conflicts:
                raise LeaseHeartbeatError(
                    "lease heartbeat row already has an active owner: "
                    + ",".join(sorted(conflicts))
                )
            for identity in identities:
                self._identity_owner[identity] = member_id
            self._active_members.add(member_id)
            if self._scheduled is not None:
                return
            heartbeat_id = self._heartbeat_id()
            phase = int.from_bytes(
                hashlib.sha256(heartbeat_id.encode("utf-8")).digest()[:8],
                "big",
            ) / float((1 << 64) - 1)
            initial_delay_seconds = self._interval_seconds * (
                0.10 + (0.80 * phase)
            )
            try:
                self._scheduled = self._heartbeat_scheduler.register(
                    self._task_group.group_id,
                    HeartbeatSpec(
                        heartbeat_id=heartbeat_id,
                        lane_id=self._lane_id,
                        interval_seconds=self._interval_seconds,
                        initial_delay_seconds=initial_delay_seconds,
                        lane_capacity=self._lane_capacity,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    self._renew_once,
                )
            except BaseException:
                self._active_members.discard(member_id)
                for identity in identities:
                    if self._identity_owner.get(identity) == member_id:
                        self._identity_owner.pop(identity, None)
                raise

    def deactivate(self, member_id: int) -> tuple[RowT, ...]:
        """Retire one guard from the live renewal workset.

        Historical ownership truth lives in Resource Authority, not here.
        Therefore a closed guard must remove its member rows completely so
        coordinator space is O(live guards), never O(historical lifetimes).
        """

        scheduled = None
        with self._lock:
            self._member_failures.pop(member_id, None)
            rows = self._rows_by_member.pop(member_id, ())
            self._active_members.discard(member_id)
            for row in rows:
                identity = self._row_identity(row)
                if self._identity_owner.get(identity) == member_id:
                    self._identity_owner.pop(identity, None)
            if self._active_members:
                return rows
            scheduled = self._scheduled
            self._scheduled = None
        if scheduled is not None:
            scheduled.cancel()
        return rows

    @property
    def active_member_count(self) -> int:
        with self._lock:
            return len(self._active_members)

    @property
    def active_member_identities(self) -> tuple[tuple[int, tuple[str, ...]], ...]:
        with self._lock:
            return tuple(
                (
                    member_id,
                    tuple(
                        self._row_identity(row)
                        for row in self._rows_by_member.get(member_id, ())
                    ),
                )
                for member_id in sorted(self._active_members)
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._active_members:
                identities = tuple(
                    (
                        member_id,
                        tuple(
                            self._row_identity(row)
                            for row in self._rows_by_member.get(member_id, ())
                        ),
                    )
                    for member_id in sorted(self._active_members)
                )
                raise LeaseHeartbeatError(
                    "cannot close lease heartbeat coordinator while "
                    f"{len(self._active_members)} live owner(s) remain: "
                    + repr(identities)
                )
            self._closed = True
            scheduled = self._scheduled
            self._scheduled = None
            self._identity_owner.clear()
            self._member_failures.clear()
        if scheduled is not None:
            scheduled.cancel()

    def _renew_batch(
        self,
        members: tuple[tuple[int, tuple[RowT, ...]], ...],
    ) -> tuple[tuple[int, tuple[RowT, ...], tuple[str, ...]], ...]:
        expected = tuple(row for _member_id, rows in members for row in rows)
        renewed = self._renew(expected)
        if type(renewed) is not tuple or len(renewed) != len(expected):
            raise RuntimeError("lease heartbeat renewal cardinality drifted")
        offset = 0
        updates: list[tuple[int, tuple[RowT, ...], tuple[str, ...]]] = []
        for member_id, rows in members:
            width = len(rows)
            replacement = renewed[offset : offset + width]
            offset += width
            updates.append(
                (
                    member_id,
                    replacement,
                    tuple(self._row_identity(row) for row in rows),
                )
            )
        return tuple(updates)

    def _renew_isolated(
        self,
        members: tuple[tuple[int, tuple[RowT, ...]], ...],
    ) -> tuple[
        tuple[tuple[int, tuple[RowT, ...], tuple[str, ...]], ...],
        tuple[tuple[int, BaseException], ...],
    ]:
        try:
            return self._renew_batch(members), ()
        except BaseException as exc:
            if len(members) == 1:
                return (), ((members[0][0], exc),)
            midpoint = len(members) // 2
            left_updates, left_failures = self._renew_isolated(
                members[:midpoint]
            )
            right_updates, right_failures = self._renew_isolated(
                members[midpoint:]
            )
            return (
                left_updates + right_updates,
                left_failures + right_failures,
            )

    def _renew_once(self, context: TaskContextPort) -> None:
        context.checkpoint()
        with self._lock:
            members = tuple(
                (member_id, self._rows_by_member[member_id])
                for member_id in sorted(self._active_members)
            )
        if not members:
            context.checkpoint()
            return

        # Attempt each aggregate batch exactly once.  If it fails, recursively
        # bisect until the failing member(s) are isolated.  Calling _renew_batch
        # here and then _renew_isolated with the same full batch would duplicate
        # Authority I/O on every failed tick and amplify lock contention.
        updates, failures = self._renew_isolated(members)

        with self._lock:
            for member_id, replacement, expected_identities in updates:
                if member_id not in self._active_members:
                    continue
                current = self._rows_by_member[member_id]
                if tuple(self._row_identity(row) for row in current) != expected_identities:
                    continue
                replacement_identities = tuple(
                    self._row_identity(row) for row in replacement
                )
                if replacement_identities != expected_identities:
                    raise RuntimeError("lease heartbeat renewal identity drifted")
                self._rows_by_member[member_id] = replacement
                # A successful renewal is authoritative proof that the member
                # recovered before ownership was lost.  Clear any prior
                # transient failure so consumers can become healthy again.
                self._member_failures.pop(member_id, None)

            for member_id, failure in failures:
                if member_id not in self._active_members:
                    continue
                # Fail closed for consumers immediately, but keep the member
                # scheduled for future renewal attempts.  Authority fencing,
                # release, generation drift, or true expiry will continue to
                # fail every attempt; transient SQLite/IO/scheduler failures can
                # recover on a later heartbeat within the lease safety window.
                # Permanently removing the member on the first exception wastes
                # the TTL redundancy and can silently orphan long-lived runs.
                self._member_failures[member_id] = failure
        context.checkpoint()

    def assert_healthy(self, member_id: int) -> None:
        with self._lock:
            failure = self._member_failures.get(member_id)
            active = member_id in self._active_members
            scheduled = self._scheduled
        if failure is not None:
            raise LeaseHeartbeatError(
                "lease heartbeat member renewal failed: "
                f"{type(failure).__name__}: {failure}"
            ) from failure
        if not active:
            return
        if self._row_expiry_epoch_s is not None:
            with self._lock:
                rows = self._rows_by_member.get(member_id, ())
            now_epoch_s = time.time()
            expired = tuple(
                self._row_identity(row)
                for row in rows
                if (expiry := self._row_expiry_epoch_s(row)) is not None
                and float(expiry) <= now_epoch_s
            )
            if expired:
                raise LeaseHeartbeatError(
                    "lease heartbeat member authority expired: "
                    + ",".join(sorted(expired))
                )
        if scheduled is None:
            raise LeaseHeartbeatError("active lease heartbeat has no scheduled renewal")
        try:
            scheduled.assert_healthy()
        except BaseException as exc:
            raise LeaseHeartbeatError(
                f"lease heartbeat failed: {type(exc).__name__}: {exc}"
            ) from exc


class LeaseHeartbeatGuard(Generic[RowT]):
    """Per-lifetime view over an authority-scoped aggregate lease heartbeat."""

    def __init__(
        self,
        *,
        coordinator: _LeaseHeartbeatBatchCoordinator[RowT],
        member_id: int,
        rows: tuple[RowT, ...],
    ) -> None:
        self._coordinator = coordinator
        self._member_id = member_id
        self._lock = Lock()
        self._rows = rows
        self._started = False
        self._closing = False
        self._closed = False

    @property
    def handles(self) -> tuple[RowT, ...]:
        with self._lock:
            if self._closed or self._closing:
                return self._rows
        rows = self._coordinator.rows(self._member_id)
        with self._lock:
            self._rows = rows
            return self._rows

    @property
    def rows(self) -> tuple[RowT, ...]:
        return self.handles

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise LeaseHeartbeatError("lease heartbeat is closed")
            if self._closing:
                raise LeaseHeartbeatError("lease heartbeat is closing")
            if self._started:
                return
            self._coordinator.activate(self._member_id)
            self._started = True

    def assert_healthy(self) -> None:
        with self._lock:
            if self._closed or not self._started:
                return
        self._coordinator.assert_healthy(self._member_id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
        rows = self._coordinator.deactivate(self._member_id)
        with self._lock:
            if rows:
                self._rows = rows
            self._closed = True
            self._closing = False


class LeaseHeartbeatFactory(Generic[RowT, PolicyT]):
    """Bind one resource authority to one aggregate renewal heartbeat."""

    def __init__(
        self,
        *,
        renew: Callable[[tuple[RowT, ...]], tuple[RowT, ...]],
        row_identity: Callable[[RowT], str],
        row_expiry_epoch_s: Callable[[RowT], float | None] | None = None,
        heartbeat_namespace: str,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        interval_seconds: float,
        policy: PolicyT,
        lane_capacity: int | None = None,
    ) -> None:
        self._coordinator = _LeaseHeartbeatBatchCoordinator(
            renew=renew,
            row_identity=row_identity,
            row_expiry_epoch_s=row_expiry_epoch_s,
            heartbeat_namespace=heartbeat_namespace,
            task_group=task_group,
            heartbeat_scheduler=heartbeat_scheduler,
            lane_id=lane_id,
            interval_seconds=interval_seconds,
            lane_capacity=lane_capacity,
        )
        self._policy = policy

    @property
    def policy(self) -> PolicyT:
        return self._policy

    @property
    def active_member_count(self) -> int:
        return self._coordinator.active_member_count

    @property
    def active_member_identities(self) -> tuple[tuple[int, tuple[str, ...]], ...]:
        return self._coordinator.active_member_identities

    def create(self, rows: tuple[RowT, ...]) -> LeaseHeartbeatGuard[RowT]:
        member_id = self._coordinator.create_member(rows)
        return LeaseHeartbeatGuard(
            coordinator=self._coordinator,
            member_id=member_id,
            rows=rows,
        )

    def close(self) -> None:
        self._coordinator.close()


__all__ = ["LeaseHeartbeatError", "LeaseHeartbeatFactory", "LeaseHeartbeatGuard"]
