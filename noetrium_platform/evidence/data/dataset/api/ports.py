from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import DatasetIdentity, DatasetQuery, DatasetVersion


@runtime_checkable
class DatasetRegistryPort(Protocol):
    def register(self, dataset: DatasetVersion) -> DatasetVersion: ...
    def get(self, identity: DatasetIdentity) -> DatasetVersion: ...
    def query(self, query: DatasetQuery = DatasetQuery()) -> tuple[DatasetVersion, ...]: ...


__all__ = ["DatasetRegistryPort"]
