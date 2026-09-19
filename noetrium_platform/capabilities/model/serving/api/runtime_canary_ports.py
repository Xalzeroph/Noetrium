from __future__ import annotations

from typing import Protocol, runtime_checkable

from .runtime_canary import RuntimeCanaryEvidence


@runtime_checkable
class RuntimeCanaryEvidenceStorePort(Protocol):
    """Immutable durable authority for live runtime canary observations."""

    def publish(
        self,
        runtime_manifest_digest: str,
        evidence: RuntimeCanaryEvidence,
    ) -> str: ...

    def load(
        self,
        runtime_manifest_digest: str,
        evidence_digest: str,
    ) -> RuntimeCanaryEvidence: ...


__all__ = ["RuntimeCanaryEvidenceStorePort"]
