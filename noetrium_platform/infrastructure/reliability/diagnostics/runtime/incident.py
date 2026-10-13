from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort, IncidentProjectionPort
from noetrium_platform.infrastructure.reliability.failure.api import fingerprint_failure

from .debug_snapshot import DebugSnapshot, DebugSnapshotService


@dataclass(frozen=True, slots=True)
class IncidentReport:
    failure_id: str
    fingerprint: str
    family_fingerprint: str
    recurrence_count: int
    family_recurrence_count: int
    recurring: bool
    family_recurring: bool
    exact_location: str
    recovery: str
    scientific_risk: str
    similar_failure_ids: tuple[str, ...]
    family_similar_failure_ids: tuple[str, ...]
    snapshot: DebugSnapshot


class IncidentService:
    """Reproducible recurrence view; evidence, recurrence projection and snapshot join are independent ports."""

    def __init__(
        self,
        evidence: DiagnosticEvidencePort,
        incidents: IncidentProjectionPort,
        snapshots: DebugSnapshotService,
    ) -> None:
        self.evidence = evidence
        self.incidents = incidents
        self.snapshots = snapshots

    def capture(self, failure_id: str, *, seconds: float = 30.0) -> IncidentReport:
        failure_record = self.evidence.locate(failure_id)
        if failure_record is None:
            raise KeyError(f"failure not found: {failure_id}")
        failure = failure_record.payload
        if "failure_domain" not in failure:
            raise KeyError(f"failure not found: {failure_id}")
        fingerprint = fingerprint_failure(failure)
        self.incidents.synchronize()
        pattern = self.incidents.get(fingerprint.fingerprint)
        if pattern is None:
            raise RuntimeError("incident projection synchronized but requested failure pattern is missing")
        snapshot = self.snapshots.build(failure_id, seconds=seconds)
        diagnosis = snapshot.diagnosis
        return IncidentReport(
            failure_id=failure_id,
            fingerprint=fingerprint.fingerprint,
            family_fingerprint=fingerprint.family_fingerprint,
            recurrence_count=pattern.count,
            family_recurrence_count=pattern.family_count,
            recurring=pattern.count > 1,
            family_recurring=pattern.family_count > 1,
            exact_location=diagnosis.exact_location if diagnosis is not None else "",
            recovery=diagnosis.recovery if diagnosis is not None else "manual_diagnosis",
            scientific_risk=diagnosis.scientific_risk if diagnosis is not None else "unknown",
            similar_failure_ids=pattern.example_failure_ids,
            family_similar_failure_ids=pattern.family_example_failure_ids,
            snapshot=snapshot,
        )
