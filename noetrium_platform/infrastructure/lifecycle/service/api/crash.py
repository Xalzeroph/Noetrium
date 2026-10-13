from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CrashClass(StrEnum):
    CLEAN_EXIT="clean_exit"
    PROCESS_SIGNAL="process_signal"
    OUT_OF_MEMORY="out_of_memory"
    GPU_DRIVER="gpu_driver"
    HEARTBEAT_LOSS="heartbeat_loss"
    SERVICE_ERROR="service_error"
    UNKNOWN="unknown"


@dataclass(frozen=True, slots=True)
class CrashEvidence:
    exit_code: int | None = None
    signal: int | None = None
    oom_killed: bool = False
    gpu_xid: int | None = None
    heartbeat_stale: bool = False
    service_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CrashDiagnosis:
    crash_class: CrashClass
    evidence: CrashEvidence
    exact_recovery_required: bool


def classify_crash(evidence: CrashEvidence) -> CrashDiagnosis:
    if evidence.oom_killed:
        crash_class=CrashClass.OUT_OF_MEMORY
    elif evidence.gpu_xid is not None:
        crash_class=CrashClass.GPU_DRIVER
    elif evidence.signal is not None:
        crash_class=CrashClass.PROCESS_SIGNAL
    elif evidence.heartbeat_stale:
        crash_class=CrashClass.HEARTBEAT_LOSS
    elif evidence.service_error_code:
        crash_class=CrashClass.SERVICE_ERROR
    elif evidence.exit_code == 0:
        crash_class=CrashClass.CLEAN_EXIT
    else:
        crash_class=CrashClass.UNKNOWN
    return CrashDiagnosis(crash_class,evidence,crash_class is not CrashClass.CLEAN_EXIT)


__all__=["CrashClass","CrashEvidence","CrashDiagnosis","classify_crash"]
