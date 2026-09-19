from __future__ import annotations

from typing import Protocol

from .evidence import EvidenceBundleManifest, EvidenceBundleReceipt


class EvidenceBundlePublisherPort(Protocol):
    def publish(self, manifest: EvidenceBundleManifest) -> EvidenceBundleReceipt: ...


__all__ = ["EvidenceBundlePublisherPort"]
