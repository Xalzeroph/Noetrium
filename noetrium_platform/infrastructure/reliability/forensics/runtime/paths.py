from __future__ import annotations

from pathlib import Path


def operation_forensics_root(operation_root: str | Path) -> Path:
    """Canonical forensic ledger root for one Operation authority."""
    return Path(operation_root) / "forensics"


def research_forensics_root(research_state_root: str | Path) -> Path:
    """Canonical forensic ledger root for one Research execution Operation authority."""
    state = Path(research_state_root)
    return operation_forensics_root(
        state / "platform-runtime" / "state" / "operations"
    )


def run_trace_forensics_root(
    research_state_root: str | Path,
    trace_partition_id: str,
) -> Path:
    """Per-run lifecycle journal; never shares a writer with OperationRuntime."""
    if type(trace_partition_id) is not str or not trace_partition_id.strip():
        raise ValueError("run trace partition id must be non-empty")
    return (
        Path(research_state_root)
        / "run-traces"
        / trace_partition_id.strip()
        / "forensics"
    )


def control_worker_forensics_root(
    control_state_root: str | Path,
    worker_partition_id: str,
) -> Path:
    if type(worker_partition_id) is not str or not worker_partition_id.strip():
        raise ValueError("control worker partition id must be non-empty")
    return (
        Path(control_state_root)
        / "control-worker-traces"
        / worker_partition_id.strip()
        / "forensics"
    )


def control_request_forensics_root(
    control_state_root: str | Path,
    request_partition_id: str,
) -> Path:
    if type(request_partition_id) is not str or not request_partition_id.strip():
        raise ValueError("control request partition id must be non-empty")
    return (
        Path(control_state_root)
        / "control-request-traces"
        / request_partition_id.strip()
        / "forensics"
    )


__all__ = [
    "control_request_forensics_root",
    "control_worker_forensics_root",
    "operation_forensics_root",
    "research_forensics_root",
    "run_trace_forensics_root",
]
