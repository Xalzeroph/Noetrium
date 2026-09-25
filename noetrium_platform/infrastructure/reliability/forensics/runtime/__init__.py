"""Provider-neutral behavior for the Forensics authority."""

from .catalog_audit import FailureCatalogAuditReport, FailureCatalogSourceAudit
from .crash_bundle import CrashBundleBuilder
from .crash_bundle_verify import verify_crash_bundle
from .diagnostic_adapter import ForensicDiagnosticEvidence
from .recorder import Breadcrumb, BreadcrumbBuffer, FailureRecordOutcome, FailureRecorder, ForensicRecordDegradation
from .triage import TriageReport, triage
from .write_lanes import CriticalWriteLane, EventWriteLane, ForensicProjectionError

__all__ = [
    "Breadcrumb",
    "BreadcrumbBuffer",
    "CrashBundleBuilder",
    "CriticalWriteLane",
    "EventWriteLane",
    "FailureCatalogAuditReport",
    "FailureCatalogSourceAudit",
    "FailureRecordOutcome",
    "FailureRecorder",
    "ForensicDiagnosticEvidence",
    "ForensicProjectionError",
    "ForensicRecordDegradation",
    "TriageReport",
    "triage",
    "verify_crash_bundle",
]
