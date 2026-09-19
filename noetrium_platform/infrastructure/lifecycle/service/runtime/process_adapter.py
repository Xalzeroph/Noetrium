from __future__ import annotations

import time

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from .capture_paths import ServiceCapturePathProvider
from .contracts import ServiceReadyEvidence
from .environment import MaterializedServiceEnvironment, ServiceEnvironmentProvider
from .prepared_start import PreparedServiceStartReconcileResult, ServiceStartRecoveryHandle
from .process_contracts import (
    ExactProcessBackend,
    ProcessReconcileStatus,
    ServiceProcessDrift,
    ServiceReadinessProbe,
)
from .process_prepared import crash_durable_prepared_process_backend
from .service_state_contracts import ServiceSupervisorState


class LocalServiceProcessAdapter:
    """Service adapter assembled from narrow environment/capture/process/readiness authorities."""

    def __init__(
        self,
        environment_provider: ServiceEnvironmentProvider,
        capture_paths: ServiceCapturePathProvider,
        process_backend: ExactProcessBackend,
        readiness_probe: ServiceReadinessProbe,
    ) -> None:
        self.environment_provider = environment_provider
        self.capture_paths = capture_paths
        self.process_backend = process_backend
        self.readiness_probe = readiness_probe

    @property
    def start_recovery_durability(self) -> str:
        return (
            "crash_durable"
            if crash_durable_prepared_process_backend(self.process_backend) is not None
            else "process_local"
        )

    def _environment(self, contract: ServiceLaunchContract) -> MaterializedServiceEnvironment:
        environment = self.environment_provider.resolve(contract.environment_digest)
        if environment.digest != contract.environment_digest:
            raise ServiceProcessDrift("materialized environment digest does not match frozen launch contract")
        return environment

    def reconcile(
        self,
        state: ServiceSupervisorState,
        contract: ServiceLaunchContract,
    ) -> tuple[ServiceProcessIdentity | None, tuple[str, ...]]:
        if state.process is None:
            return None, ()
        environment = self._environment(contract)
        result = self.process_backend.reconcile(state.process, contract, environment)
        refs = (environment.evidence_ref,) + tuple(result.evidence_refs)
        if result.status is ProcessReconcileStatus.EXACT:
            return state.process, refs
        if result.status is ProcessReconcileStatus.MISSING:
            return None, refs
        raise ServiceProcessDrift(result.reason or "persisted service process drifted from frozen contract")

    def start(self, contract: ServiceLaunchContract) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        environment = self._environment(contract)
        captures = self.capture_paths.paths(contract)
        process, refs = self.process_backend.start(contract, environment, captures)
        return process, (environment.evidence_ref, captures.stdout_ref, captures.stderr_ref) + tuple(refs)

    def prepare_start_recovery(
        self,
        contract: ServiceLaunchContract,
        *,
        intent_id: str,
        attempt: int,
    ) -> ServiceStartRecoveryHandle:
        backend = crash_durable_prepared_process_backend(self.process_backend)
        if backend is None:
            raise RuntimeError("process backend does not provide crash-durable prepared start")
        environment = self._environment(contract)
        captures = self.capture_paths.paths(contract)
        return backend.prepare_start_recovery(
            contract,
            environment,
            captures,
            intent_id=intent_id,
            attempt=attempt,
        )

    def start_prepared(
        self,
        contract: ServiceLaunchContract,
        handle: ServiceStartRecoveryHandle,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        backend = crash_durable_prepared_process_backend(self.process_backend)
        if backend is None:
            raise RuntimeError("process backend does not provide crash-durable prepared start")
        environment = self._environment(contract)
        captures = self.capture_paths.paths(contract)
        process, refs = backend.start_prepared(contract, environment, captures, handle)
        return process, (environment.evidence_ref, captures.stdout_ref, captures.stderr_ref) + tuple(refs)

    def reconcile_prepared_start(
        self,
        contract: ServiceLaunchContract,
        handle: ServiceStartRecoveryHandle,
    ) -> PreparedServiceStartReconcileResult:
        backend = crash_durable_prepared_process_backend(self.process_backend)
        if backend is None:
            raise RuntimeError("process backend does not provide crash-durable prepared start")
        environment = self._environment(contract)
        captures = self.capture_paths.paths(contract)
        return backend.reconcile_prepared_start(contract, environment, captures, handle)

    def wait_ready(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> ServiceReadyEvidence:
        captures = self.capture_paths.paths(contract)
        ready_ref = self.readiness_probe.wait_ready(process, contract, self.process_backend)
        return ServiceReadyEvidence(
            contract_digest=contract.digest(),
            process=process,
            readiness_ref=ready_ref,
            stdout_capture_ref=captures.stdout_ref,
            stderr_capture_ref=captures.stderr_ref,
            ready_at=time.time(),
        )

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        return tuple(self.process_backend.stop(process, contract))


__all__ = ["LocalServiceProcessAdapter"]
