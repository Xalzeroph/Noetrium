from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort, MetricQueryPort
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import (
    CausalGraphService,
    DebugSnapshotService,
    EvidenceVerifier,
    FailureDiagnosisService,
    RuntimeRecoveryDecisionService,
    TriagePlanService,
)
from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.evidence.observability.status.api import PlatformStatus
from noetrium_platform.evidence.observability.status.runtime import JsonStateStatusProbe, PlatformStatusService
from noetrium_platform.infrastructure.reliability.forensics.runtime import CrashBundleBuilder, verify_crash_bundle
from noetrium_platform.infrastructure.reliability.forensics.composition import ForensicStore, inspect_index_freshness, rebuild_forensic_index
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.evidence.observability.telemetry.metric.providers import MetricSummary, SQLiteTelemetryReader


@contextmanager
def open_diagnostic_evidence(root: Path) -> Iterator[DiagnosticEvidencePort]:
    """Open one bounded read-only diagnostic evidence session."""

    with ForensicStore(root, read_only=True, task_group=None) as store:
        yield ForensicDiagnosticEvidence(store)


def inspect_diagnostic_index(root: Path):
    return inspect_index_freshness(root)


def rebuild_diagnostic_index(root: Path):
    runtime = build_concurrency_runtime()
    try:
        group = runtime.open_task_group("diagnostic-forensics-index-rebuild")
        return rebuild_forensic_index(root, task_group=group)
    finally:
        runtime.close()


def publish_crash_bundle(root: Path, failure_id: str, output: Path):
    with ForensicStore(root, read_only=True, task_group=None) as store:
        return CrashBundleBuilder(store).publish(failure_id, output)


def verify_crash_bundle_artifact(path: Path):
    return verify_crash_bundle(path)


def metric_query_backend(path: Path) -> MetricQueryPort:
    return SQLiteTelemetryReader(path)



def verify_diagnostic_evidence(evidence: DiagnosticEvidencePort):
    return EvidenceVerifier(evidence).verify()


def build_diagnostic_status(
    evidence: DiagnosticEvidencePort,
    *,
    model_state: Path | None = None,
    study_state: Path | None = None,
) -> PlatformStatus:
    probes = [ForensicStatusProbe(evidence)]
    if model_state is not None:
        probes.append(JsonStateStatusProbe("model", model_state))
    if study_state is not None:
        probes.append(JsonStateStatusProbe("study", study_state))
    return PlatformStatusService(probes).snapshot()


def locate_diagnostic_object(evidence: DiagnosticEvidencePort, object_id: str):
    return FailureDiagnosisService(evidence).locate(object_id)


def diagnose_failure(evidence: DiagnosticEvidencePort, failure_id: str):
    return FailureDiagnosisService(evidence).why(failure_id)


def build_causal_graph(evidence: DiagnosticEvidencePort, object_id: str, *, related_limit: int = 200):
    return CausalGraphService(evidence).build(object_id, related_limit=related_limit)


def diagnostic_timeline(evidence: DiagnosticEvidencePort, object_id: str, *, seconds: float):
    return FailureDiagnosisService(evidence).timeline(object_id, seconds=seconds)


def diagnostic_last_writer(evidence: DiagnosticEvidencePort, run_id: str, state_name: str):
    return FailureDiagnosisService(evidence).last_writer(run_id, state_name)


def build_debug_snapshot(
    evidence: DiagnosticEvidencePort,
    object_id: str,
    *,
    seconds: float,
    telemetry_db: Path | None = None,
    metric_limit: int = 200,
):
    metrics = metric_query_backend(telemetry_db) if telemetry_db is not None else None
    return DebugSnapshotService(evidence, metrics).build(
        object_id,
        seconds=seconds,
        metric_limit=metric_limit,
    )


def build_triage_plan(evidence: DiagnosticEvidencePort, failure_id: str):
    return TriagePlanService(evidence).build(failure_id)


def build_runtime_recovery_plan(status: PlatformStatus) -> dict[str, object]:
    decisions = RuntimeRecoveryDecisionService().plan(status)
    return {
        "schema_version": "runtime-recovery-plan.v1",
        "status": status.to_dict(),
        "recovery": decisions.to_dict(),
    }

def query_metrics(
    path: Path,
    *,
    run_id: str,
    metric: str | None = None,
    decision_cycle_id: str | None = None,
    limit: int = 1000,
) -> tuple[dict[str, object], ...]:
    return SQLiteTelemetryReader(path).query(
        run_id=run_id,
        metric=metric,
        decision_cycle_id=decision_cycle_id,
        limit=limit,
    )


def summarize_metrics(path: Path, *, run_id: str, metric: str) -> MetricSummary:
    return SQLiteTelemetryReader(path).summarize(run_id=run_id, metric=metric)


__all__ = [
    "build_causal_graph",
    "build_debug_snapshot",
    "build_diagnostic_status",
    "build_runtime_recovery_plan",
    "build_triage_plan",
    "diagnose_failure",
    "diagnostic_last_writer",
    "diagnostic_timeline",
    "inspect_diagnostic_index",
    "locate_diagnostic_object",
    "metric_query_backend",
    "open_diagnostic_evidence",
    "publish_crash_bundle",
    "query_metrics",
    "rebuild_diagnostic_index",
    "summarize_metrics",
    "verify_crash_bundle_artifact",
    "verify_diagnostic_evidence",
]
