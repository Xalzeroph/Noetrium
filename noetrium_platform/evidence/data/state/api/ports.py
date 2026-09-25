from __future__ import annotations
from typing import Protocol, runtime_checkable
from .contracts import AggregateValue, AtomicMutation

@runtime_checkable
class AtomicStateStorePort(Protocol):
    def read(self, aggregate_id: str) -> AggregateValue: ...
    def commit_batch(self, mutations: tuple[AtomicMutation, ...]) -> tuple[AggregateValue, ...]: ...

__all__=["AtomicStateStorePort"]
