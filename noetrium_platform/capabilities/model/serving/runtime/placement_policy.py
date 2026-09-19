from __future__ import annotations

from itertools import combinations

from noetrium_platform.capabilities.model.serving.api import GPUInventory, HostInventory
from noetrium_platform.capabilities.model.serving.api.placement import GpuPlacementPolicyPort


class ExactFabricPlacementPolicy(GpuPlacementPolicyPort):
    """Exact topology preference with indexed fabric lookup and O(1) extra group memory.

    The search space remains exact (all C(n,k) feasible groups are considered), but
    fabric lookup is pre-indexed once and groups are streamed through ``max`` rather
    than materialized and sorted.  For each group the cost is O(k²), independent of
    the total number of fabric links.
    """

    @staticmethod
    def _fabric_index(host: HostInventory) -> dict[tuple[str, str], float]:
        index: dict[tuple[str, str], float] = {}
        for link in host.fabric:
            key = tuple(sorted((link.a_uuid, link.b_uuid)))
            # Multiple reported links between the same pair contribute exactly as
            # the old first-match semantics only when inventory contains duplicates.
            # Host inventories are expected to expose one aggregate edge; retain the
            # first edge deterministically to preserve legacy behavior.
            index.setdefault(key, link.bandwidth_gbps)
        return index

    def select(
        self,
        host: HostInventory,
        candidates: tuple[GPUInventory, ...],
        count: int,
    ) -> tuple[GPUInventory, ...]:
        if count <= 0:
            raise ValueError("GPU placement count must be positive")
        if len(candidates) < count:
            raise ValueError("insufficient GPU candidates")
        if count == 1:
            # Same ordering as max(..., key=(0, -numa_count, uuid_tuple)).
            return (max(candidates, key=lambda gpu: gpu.uuid),)

        fabric = self._fabric_index(host)

        def key(group: tuple[GPUInventory, ...]) -> tuple[float, int, tuple[str, ...]]:
            score = 0.0
            for idx, first in enumerate(group[:-1]):
                for second in group[idx + 1 :]:
                    score += fabric.get(tuple(sorted((first.uuid, second.uuid))), 0.0)
            numa_count = len({gpu.numa_node for gpu in group if gpu.numa_node is not None})
            return score, -numa_count, tuple(gpu.uuid for gpu in group)

        return max(combinations(candidates, count), key=key)


__all__ = ["ExactFabricPlacementPolicy"]
