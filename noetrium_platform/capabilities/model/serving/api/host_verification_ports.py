from __future__ import annotations

from typing import Protocol, runtime_checkable

from .inventory import HostInventory
from .host_verification import HostInventoryReceipt, HostResourceDelta


@runtime_checkable
class HostInventoryProvider(Protocol):
    def capture(self) -> HostInventory: ...


class HostInventoryEvidenceStorePort(Protocol):
    def publish(self, runtime_manifest_digest: str, receipt: HostInventoryReceipt) -> str: ...

    def load(self, runtime_manifest_digest: str, phase: str) -> HostInventoryReceipt: ...

    def publish_delta(self, runtime_manifest_digest: str, delta: HostResourceDelta) -> str: ...


__all__ = ["HostInventoryEvidenceStorePort", "HostInventoryProvider"]
