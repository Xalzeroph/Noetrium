"""Pure indexed projection of resource topology.

No durable state and no physical effects live here. The sole NoetriumUnit owns
resource dependency truth. Authority consumes these derived closures/frontiers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Iterable, Mapping

from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from .topology import (
    RESOURCE_REQUIRES_RELATION,
    resource_acquire_order,
    resource_authority_key,
    resource_kind,
    resource_requires_realization,
)


def _prerequisites(topology: NoetriumUnit) -> dict[str, tuple[str, ...]]:
    rows: dict[str, list[str]] = {
        child.unit_id: [] for child in topology.members
    }
    for relation in topology.relations:
        if relation.relation_id != RESOURCE_REQUIRES_RELATION:
            continue
        for source in relation.sources:
            for target in relation.targets:
                rows[source.child_id].append(target.child_id)
    return {
        key: tuple(sorted(set(value)))
        for key, value in rows.items()
    }


def _dependents(
    prerequisites: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    rows: dict[str, list[str]] = {key: [] for key in prerequisites}
    for dependent, required in prerequisites.items():
        for prerequisite in required:
            rows[prerequisite].append(dependent)
    return {
        key: tuple(sorted(set(value)))
        for key, value in rows.items()
    }


@dataclass(frozen=True, slots=True)
class ResourceTopologyIndex:
    """Pure indexed projection from one resource topology Unit to dependency semantics."""

    topology: NoetriumUnit
    _acquire_order: tuple[str, ...] = field(init=False, repr=False)
    _release_order: tuple[str, ...] = field(init=False, repr=False)
    _acquire_rank: Mapping[str, int] = field(init=False, repr=False)
    _release_rank: Mapping[str, int] = field(init=False, repr=False)
    _prerequisite_index: Mapping[str, tuple[str, ...]] = field(
        init=False,
        repr=False,
    )
    _dependent_index: Mapping[str, tuple[str, ...]] = field(
        init=False,
        repr=False,
    )
    _kind_index: Mapping[str, str] = field(init=False, repr=False)
    _authority_key_index: Mapping[str, str] = field(init=False, repr=False)
    _realization_index: Mapping[str, bool] = field(init=False, repr=False)
    _node_index: Mapping[str, NoetriumUnit] = field(
        init=False,
        repr=False,
    )
    _resource_ids: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        acquire = resource_acquire_order(self.topology)
        prerequisites = _prerequisites(self.topology)
        object.__setattr__(self, "_acquire_order", acquire)
        release = tuple(reversed(acquire))
        object.__setattr__(self, "_release_order", release)
        object.__setattr__(
            self,
            "_acquire_rank",
            MappingProxyType({resource_id: index for index, resource_id in enumerate(acquire)}),
        )
        object.__setattr__(
            self,
            "_release_rank",
            MappingProxyType({resource_id: index for index, resource_id in enumerate(release)}),
        )
        object.__setattr__(
            self,
            "_prerequisite_index",
            MappingProxyType(prerequisites),
        )
        object.__setattr__(
            self,
            "_dependent_index",
            MappingProxyType(_dependents(prerequisites)),
        )
        object.__setattr__(
            self,
            "_kind_index",
            MappingProxyType(
                {
                    child.unit_id: resource_kind(child)
                    for child in self.topology.members
                }
            ),
        )
        object.__setattr__(
            self,
            "_authority_key_index",
            MappingProxyType(
                {
                    child.unit_id: resource_authority_key(child)
                    for child in self.topology.members
                }
            ),
        )
        if len(set(self._authority_key_index.values())) != len(self._authority_key_index):
            raise ValueError("resource topology authority keys must be unique")
        object.__setattr__(
            self,
            "_realization_index",
            MappingProxyType(
                {
                    child.unit_id: resource_requires_realization(child)
                    for child in self.topology.members
                }
            ),
        )
        object.__setattr__(
            self,
            "_node_index",
            MappingProxyType(
                {child.unit_id: child for child in self.topology.members}
            ),
        )
        object.__setattr__(
            self,
            "_resource_ids",
            frozenset(self._node_index),
        )

    @property
    def acquire_order(self) -> tuple[str, ...]:
        return self._acquire_order

    @property
    def release_order(self) -> tuple[str, ...]:
        return self._release_order

    @property
    def resource_ids(self) -> frozenset[str]:
        return self._resource_ids

    def node(self, resource_id: str) -> NoetriumUnit:
        try:
            return self._node_index[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource node: {resource_id}") from exc

    def kind(self, resource_id: str) -> str:
        try:
            return self._kind_index[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource node: {resource_id}") from exc

    def authority_key(self, resource_id: str) -> str:
        try:
            return self._authority_key_index[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource node: {resource_id}") from exc

    def requires_realization(self, resource_id: str) -> bool:
        try:
            return self._realization_index[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource node: {resource_id}") from exc

    def prerequisites(self, resource_id: str) -> tuple[str, ...]:
        try:
            return self._prerequisite_index[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource node: {resource_id}") from exc

    def dependents(self, resource_id: str) -> tuple[str, ...]:
        try:
            return self._dependent_index[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown resource node: {resource_id}") from exc

    def ready_frontier(
        self,
        satisfied: frozenset[str],
    ) -> tuple[str, ...]:
        if type(satisfied) is not frozenset:
            raise TypeError("resource frontier requires frozenset")
        known = self.resource_ids
        if not satisfied <= known:
            raise ValueError(
                "resource frontier satisfaction contains unknown resource ids"
            )
        return tuple(
            resource_id
            for resource_id in self.acquire_order
            if resource_id not in satisfied
            and all(
                prerequisite in satisfied
                for prerequisite in self._prerequisite_index[resource_id]
            )
        )

    def dependency_closure(
        self,
        resource_ids: Iterable[str],
    ) -> frozenset[str]:
        pending = list(resource_ids)
        closure: set[str] = set()
        while pending:
            resource_id = pending.pop()
            if resource_id not in self._node_index:
                raise KeyError(f"unknown resource node: {resource_id}")
            if resource_id in closure:
                continue
            closure.add(resource_id)
            pending.extend(self._prerequisite_index[resource_id])
        return frozenset(closure)

    def reverse_dependency_closure(
        self,
        resource_ids: Iterable[str],
    ) -> frozenset[str]:
        pending = list(resource_ids)
        closure: set[str] = set()
        while pending:
            resource_id = pending.pop()
            if resource_id not in self._node_index:
                raise KeyError(f"unknown resource node: {resource_id}")
            if resource_id in closure:
                continue
            closure.add(resource_id)
            pending.extend(self._dependent_index[resource_id])
        return frozenset(closure)

    @staticmethod
    def _ordered_subset(
        selected: frozenset[str],
        order: tuple[str, ...],
        rank: Mapping[str, int],
    ) -> tuple[str, ...]:
        if not selected:
            return ()
        # Sparse retirement/rebuild sets are common. Sorting only k selected
        # ranks costs O(k log k), while filtering the full topology costs O(V).
        # Dense sets keep the linear scan, so the optimization never turns a
        # full-graph operation into O(V log V).
        sparse_cost = len(selected) * max(1, len(selected).bit_length())
        if sparse_cost < len(order):
            return tuple(sorted(selected, key=rank.__getitem__))
        return tuple(resource_id for resource_id in order if resource_id in selected)

    def acquire_subset(
        self,
        resource_ids: Iterable[str],
    ) -> tuple[str, ...]:
        selected = frozenset(resource_ids)
        if not selected <= self.resource_ids:
            raise KeyError(
                "resource acquire subset contains unknown resource ids"
            )
        return self._ordered_subset(
            selected,
            self.acquire_order,
            self._acquire_rank,
        )

    def release_subset(
        self,
        resource_ids: Iterable[str],
    ) -> tuple[str, ...]:
        selected = frozenset(resource_ids)
        if not selected <= self.resource_ids:
            raise KeyError(
                "resource release subset contains unknown resource ids"
            )
        return self._ordered_subset(
            selected,
            self.release_order,
            self._release_rank,
        )


__all__ = ["ResourceTopologyIndex"]
