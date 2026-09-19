from __future__ import annotations

import heapq

from noetrium_platform.evidence.data.dataset.api import (
    DatasetIdentity,
    DatasetNotFound,
    DatasetQuery,
    DatasetRegistryConflict,
    DatasetVersion,
)


class InMemoryDatasetRegistry:
    def __init__(self) -> None:
        self._items: dict[str, DatasetVersion] = {}

    def register(self, dataset: DatasetVersion) -> DatasetVersion:
        current = self._items.get(dataset.identity.key)
        if current is not None and current != dataset:
            raise DatasetRegistryConflict(dataset.identity.key)
        self._items[dataset.identity.key] = dataset
        return dataset

    def get(self, identity: DatasetIdentity) -> DatasetVersion:
        try:
            return self._items[identity.key]
        except KeyError as exc:
            raise DatasetNotFound(identity.key) from exc

    def query(self, query: DatasetQuery = DatasetQuery()) -> tuple[DatasetVersion, ...]:
        rows = self._items.values()
        if query.dataset_id is not None:
            rows = (row for row in rows if row.identity.dataset_id == query.dataset_id)
        if query.scope is not None:
            rows = (row for row in rows if row.scope == query.scope)
        if query.tag is not None:
            rows = (row for row in rows if query.tag in row.tags)
        return tuple(heapq.nsmallest(query.limit, rows, key=lambda row: row.identity.key))


__all__ = ["InMemoryDatasetRegistry"]
