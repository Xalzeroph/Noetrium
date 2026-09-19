from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from dataclasses import dataclass
import hashlib
from typing import Protocol

from noetrium_platform.infrastructure.lifecycle.process.api import CaptureManifest, CaptureSyncReceipt, ProcessByteCapturePort
from noetrium_platform.infrastructure.reliability.primitives import CrashClass, CrashDiagnosis, CrashEvidence, classify_crash

from .contracts import ServiceExitClass


class ServiceCrashEvidenceAdapter(Protocol):
    """Acquires crash evidence without owning service lifecycle or recovery policy."""

    def inspect_crash(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> CrashEvidence: ...

    def captures(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[ProcessByteCapturePort, ProcessByteCapturePort]: ...


@dataclass(frozen=True, slots=True)
class CaptureTailRef:
    stream: str
    start_offset: int
    length: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CrashCaptureEvidence:
    stdout_sync: CaptureSyncReceipt
    stderr_sync: CaptureSyncReceipt
    stdout_manifest: CaptureManifest
    stderr_manifest: CaptureManifest
    stdout_manifest_ref: str
    stderr_manifest_ref: str
    stdout_tail: CaptureTailRef
    stderr_tail: CaptureTailRef


@dataclass(frozen=True, slots=True)
class ServiceCrashReport:
    service_id: str
    contract_digest: str
    process: ServiceProcessIdentity
    diagnosis: CrashDiagnosis
    exit_class: ServiceExitClass
    capture: CrashCaptureEvidence
    evidence_refs: tuple[str, ...]


def service_exit_class(diagnosis: CrashDiagnosis) -> ServiceExitClass:
    cls = diagnosis.crash_class
    if cls is CrashClass.CLEAN_EXIT:
        return ServiceExitClass.CLEAN
    if cls in {
        CrashClass.PROCESS_SIGNAL,
        CrashClass.OUT_OF_MEMORY,
        CrashClass.GPU_DRIVER,
        CrashClass.HEARTBEAT_LOSS,
    }:
        # TEMPORARY means "eligible for the bounded exact-restart policy".
        # It does not authorize model/precision/context drift.
        return ServiceExitClass.TEMPORARY
    return ServiceExitClass.SOFTWARE


def _tail_ref(capture: ProcessByteCapturePort, manifest: CaptureManifest) -> CaptureTailRef:
    tail = capture.tail()
    return CaptureTailRef(
        stream=manifest.stream,
        start_offset=max(0, manifest.total_bytes - len(tail)),
        length=len(tail),
        sha256=hashlib.sha256(tail).hexdigest(),
    )


def freeze_crash_evidence(
    process: ServiceProcessIdentity,
    contract: ServiceLaunchContract,
    adapter: ServiceCrashEvidenceAdapter,
) -> tuple[CrashDiagnosis, CrashCaptureEvidence]:
    """Freeze process logs before deciding recovery.

    The ordering is deliberate:
      1. inspect the process;
      2. fsync both streams to establish a crash cut;
      3. seal immutable manifests;
      4. classify the crash.

    No recovery action is executed here.
    """

    raw = adapter.inspect_crash(process, contract)
    stdout_capture, stderr_capture = adapter.captures(process, contract)

    stdout_sync = stdout_capture.sync()
    stderr_sync = stderr_capture.sync()
    stdout_manifest = stdout_capture.seal()
    stderr_manifest = stderr_capture.seal()

    evidence = CrashCaptureEvidence(
        stdout_sync=stdout_sync,
        stderr_sync=stderr_sync,
        stdout_manifest=stdout_manifest,
        stderr_manifest=stderr_manifest,
        stdout_manifest_ref=stdout_capture.manifest_reference(),
        stderr_manifest_ref=stderr_capture.manifest_reference(),
        stdout_tail=_tail_ref(stdout_capture, stdout_manifest),
        stderr_tail=_tail_ref(stderr_capture, stderr_manifest),
    )
    return classify_crash(raw), evidence
