from __future__ import annotations

from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort
from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot


class ForensicStatusProbe:
    def __init__(self, source: DiagnosticEvidencePort) -> None:
        self._source = source

    def snapshot(self) -> SubsystemSnapshot:
        verified = self._source.verify_authoritative()
        fresh, ledgers, indexed = self._source.projection_freshness()
        refs = tuple(
            f"{name}:rows={rows}:tail={tail}"
            for name, (rows, tail) in sorted(verified.items())
        )
        if not fresh:
            return SubsystemSnapshot(
                "forensics",
                HealthState.DEGRADED_EVIDENCE,
                f"authoritative ledgers valid but projection stale: ledger={ledgers} index={indexed}",
                evidence=refs,
                next_commands=("rebuild forensic projection from authoritative ledgers",),
                reason_codes=("forensic_projection_stale",),
            )

        unclosed = self._source.unclosed_operations(limit=100)
        return SubsystemSnapshot(
            "forensics",
            HealthState.READY,
            f"authoritative ledgers verified; disposable projection fresh; unclosed_operation_invocations={len(unclosed)}",
            evidence=refs,
            next_commands=("noetrium-forensics unclosed-operations RUN_ROOT",) if unclosed else (),
            reason_codes=(("unclosed_operation_invocations",) if unclosed else ()),
        )


__all__ = ["ForensicStatusProbe"]
