from __future__ import annotations

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG, FailureEnvelope, build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from noetrium_platform.infrastructure.reliability.primitives import CrashClass
from noetrium_platform.infrastructure.lifecycle.service.runtime.crash_capture import CaptureTailRef, ServiceCrashReport


class ServiceCrashDetected(RuntimeError):
    """Stable integration cause produced from an already-frozen service crash report."""

    def __init__(self, report: ServiceCrashReport) -> None:
        evidence = report.diagnosis.evidence
        parts = [
            f"service={report.service_id}",
            f"crash_class={report.diagnosis.crash_class.value}",
        ]
        if evidence.exit_code is not None:
            parts.append(f"exit_code={evidence.exit_code}")
        if evidence.signal is not None:
            parts.append(f"signal={evidence.signal}")
        if evidence.gpu_xid is not None:
            parts.append(f"gpu_xid={evidence.gpu_xid}")
        if evidence.service_error_code is not None:
            parts.append(f"service_error_code={evidence.service_error_code}")
        super().__init__(" ".join(parts))


SERVICE_CRASH_FAILURE_CODES = {
    CrashClass.PROCESS_SIGNAL: "MODEL_SERVICE_SIGNAL",
    CrashClass.OUT_OF_MEMORY: "MODEL_SERVICE_OOM",
    CrashClass.GPU_DRIVER: "MODEL_SERVICE_GPU_DRIVER",
    CrashClass.HEARTBEAT_LOSS: "MODEL_SERVICE_HEARTBEAT_LOSS",
    CrashClass.SERVICE_ERROR: "MODEL_SERVICE_ERROR",
    CrashClass.UNKNOWN: "MODEL_SERVICE_UNKNOWN_EXIT",
}


def _tail_uri(ref: CaptureTailRef) -> str:
    return (
        f"capture-tail://{ref.stream}"
        f"?start={ref.start_offset}&length={ref.length}&sha256={ref.sha256}"
    )


def service_crash_failure(report: ServiceCrashReport, context: ExecutionContext) -> FailureEnvelope:
    """Map Service OS crash facts into platform failure taxonomy; no persistence side effects."""

    crash_class = report.diagnosis.crash_class
    if crash_class is CrashClass.CLEAN_EXIT:
        raise ValueError("clean service exit is not a failure")
    spec = DEFAULT_FAILURE_CATALOG.require(
        "MODEL_SERVING",
        SERVICE_CRASH_FAILURE_CODES[crash_class],
        "service_process_exit",
    )
    process = report.process
    process_ref = (
        f"process://pid={process.pid}"
        f"?start_identity={process.start_identity}"
        f"&process_group_id={process.process_group_id}"
    )
    contract_ref = f"service-contract://sha256={report.contract_digest}"
    artifacts = (
        contract_ref,
        process_ref,
        report.capture.stdout_manifest_ref,
        report.capture.stderr_manifest_ref,
        _tail_uri(report.capture.stdout_tail),
        _tail_uri(report.capture.stderr_tail),
    )
    return build_failure_from_spec(
        spec=spec,
        component_id=report.service_id,
        context=context,
        exc=ServiceCrashDetected(report),
        operation_id=context.operation_id,
        operation_type="model_service_process",
        retryability="exact_restart_only",
        recoverability="recovery_required",
        input_artifacts=(contract_ref, process_ref),
        output_artifacts=artifacts[2:],
    )


__all__ = ["SERVICE_CRASH_FAILURE_CODES", "ServiceCrashDetected", "service_crash_failure"]
