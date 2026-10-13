from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .contracts import SchedulingCandidate


class SchedulingAuthorityPort(Protocol):
    """Own global scheduling order/accounting, never physical capacity."""

    def service_revision(self) -> int:
        """Current committed service-history generation for selection caches."""
        ...

    def service_changes_since(
        self, revision: int | None,
    ) -> tuple[int, frozenset[str] | None]:
        """Read one authority cut and changed flow ids; None means rebuild.

        The flow-only delta is valid for candidates sharing a tenant/resource.
        A missing event window or a wider-scope change requires a full refresh.
        """
        ...

    def ordering_key(
        self,
        candidate: SchedulingCandidate,
        *,
        now_monotonic: float,
    ) -> tuple[int | float, ...]: ...

    def ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        """Evaluate one coherent scheduling cut for an entire Unit batch."""
        ...

    def ordering_keys_at_revision(
        self, candidates: tuple[SchedulingCandidate, ...], *,
        now_monotonic: float, known_revision: int | None = None,
    ) -> tuple[int, tuple[tuple[int | float, ...], ...] | None]:
        """Version and ranking from one cut; None reuses that exact revision."""
        ...

    def ordering_projection_pairs(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[
        tuple[tuple[int | float, ...], tuple[int | float, ...]], ...
    ]:
        """(within-flow key, between-flow key) from one authority cut."""
        ...

    def within_flow_ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        """Canonical candidate ordering with shared flow counters removed."""
        ...

    def flow_relative_ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        """Same fairness law with shared parent coordinates factored out."""
        ...

    def select(
        self,
        candidates: Iterable[SchedulingCandidate],
        *,
        now_monotonic: float,
    ) -> int: ...

    def record_grant(
        self,
        *,
        tenant_id: str | None,
        flow_id: str,
        resource_id: str | None = None,
        permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> int: ...

    def record_completion(
        self,
        *,
        tenant_id: str | None,
        flow_id: str,
        service_quanta: int,
        resource_id: str | None = None,
        permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> None: ...

    def rollback_grant(
        self,
        *,
        tenant_id: str | None,
        flow_id: str,
        resource_id: str | None = None,
        permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> None:
        """Undo a grant that never reached physical execution."""
        ...

    def release_flow(
        self, flow_id: str, *, tenant_id: str | None,
        resource_id: str | None = None,
    ) -> None: ...
    def release_resource(
        self,
        *,
        tenant_id: str | None,
        resource_id: str,
    ) -> None: ...
