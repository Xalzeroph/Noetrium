from __future__ import annotations

from typing import Protocol

from .runtime_qualification import RuntimeQualificationReceipt


class RuntimeQualificationEvidenceStorePort(Protocol):
    """Durable Model-OS storage boundary for runtime qualification receipts."""

    def publish(self, runtime_manifest_digest: str, receipt: RuntimeQualificationReceipt) -> str: ...

    def load(self, runtime_manifest_digest: str, deployment_id: str) -> RuntimeQualificationReceipt: ...


__all__ = ["RuntimeQualificationEvidenceStorePort"]
