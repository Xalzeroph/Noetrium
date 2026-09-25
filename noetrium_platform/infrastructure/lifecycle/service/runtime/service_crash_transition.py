from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity, ServiceContractDrift
from .contracts import ServiceExitClass, ServicePhase
from .crash_capture import ServiceCrashEvidenceAdapter, ServiceCrashReport, freeze_crash_evidence, service_exit_class
from .service_observation import ServiceObservationCoordinator
from .service_state_contracts import ServiceSupervisorState
from .state_transition import ServiceStateTransitionWriter


class ServiceCrashTransitionCoordinator:
    """Freeze crash evidence and commit exact crash state transitions only."""

    def __init__(
        self,
        observation: ServiceObservationCoordinator,
        transitions: ServiceStateTransitionWriter,
    ) -> None:
        self._observation = observation
        self._transitions = transitions

    def _crash_state(self, contract: ServiceLaunchContract) -> ServiceSupervisorState:
        state = self._observation.observe_state(contract)
        if state is None:
            raise RuntimeError("service supervisor state is missing")
        if state.process is None:
            raise RuntimeError("cannot inspect unexpected exit without a persisted process identity")
        if state.phase not in {ServicePhase.RUNNING, ServicePhase.WAIT_READY}:
            raise RuntimeError(f"unexpected exit cannot be handled from phase {state.phase}")
        return state

    def prepare_unexpected_exit(
        self,
        contract: ServiceLaunchContract,
        crash_adapter: ServiceCrashEvidenceAdapter,
    ) -> ServiceCrashReport:
        state = self._crash_state(contract)
        assert state.process is not None
        process = state.process
        diagnosis, capture = freeze_crash_evidence(process, contract, crash_adapter)
        exit_class = service_exit_class(diagnosis)
        refs = (
            capture.stdout_manifest_ref,
            capture.stderr_manifest_ref,
            f"stdout-tail:{capture.stdout_tail.sha256}",
            f"stderr-tail:{capture.stderr_tail.sha256}",
        )
        return ServiceCrashReport(
            service_id=contract.service_id,
            contract_digest=contract.digest(),
            process=process,
            diagnosis=diagnosis,
            exit_class=exit_class,
            capture=capture,
            evidence_refs=refs,
        )

    def commit_clean_exit(
        self,
        contract: ServiceLaunchContract,
        report: ServiceCrashReport,
    ) -> ServiceSupervisorState:
        if report.exit_class is not ServiceExitClass.CLEAN:
            raise RuntimeError("non-clean service exit requires durable crash handoff with failure identity")
        state = self._crash_state(contract)
        if report.contract_digest != contract.digest() or report.service_id != contract.service_id:
            raise ServiceContractDrift("clean exit report does not match immutable launch contract")
        if state.process != report.process:
            raise RuntimeError("persisted process identity changed after clean-exit evidence was frozen")
        return self._transitions.persist(
            state,
            ServicePhase.EXITED,
            process=None,
            stdout_capture_ref=report.capture.stdout_manifest_ref,
            stderr_capture_ref=report.capture.stderr_manifest_ref,
            last_exit_class=ServiceExitClass.CLEAN,
        )

    def commit_handoff_transition(
        self,
        contract: ServiceLaunchContract,
        *,
        process: ServiceProcessIdentity,
        exit_class: ServiceExitClass,
        stdout_capture_ref: str,
        stderr_capture_ref: str,
        failure_id: str | None = None,
    ) -> ServiceSupervisorState:
        state = self._observation.observe_state(contract)
        if state is None:
            raise RuntimeError("service supervisor state is missing")
        target = ServicePhase.EXITED if exit_class is ServiceExitClass.CLEAN else ServicePhase.RECOVERY_REQUIRED
        if exit_class is not ServiceExitClass.CLEAN and not failure_id:
            raise RuntimeError("non-clean crash handoff requires durable failure identity")

        if state.process is None and state.phase is target:
            if state.stdout_capture_ref != stdout_capture_ref or state.stderr_capture_ref != stderr_capture_ref:
                raise RuntimeError("committed crash state disagrees with durable handoff capture refs")
            if state.last_exit_class is not exit_class:
                raise RuntimeError("committed crash state disagrees with durable handoff exit class")
            if failure_id is not None and state.last_failure_id != failure_id:
                raise RuntimeError("committed crash state disagrees with durable handoff failure id")
            return state

        if state.process != process:
            raise RuntimeError("cannot commit crash handoff: process identity changed")
        if state.phase not in {ServicePhase.RUNNING, ServicePhase.WAIT_READY}:
            raise RuntimeError(f"cannot commit crash handoff from phase {state.phase}")
        return self._transitions.persist(
            state,
            target,
            process=None,
            stdout_capture_ref=stdout_capture_ref,
            stderr_capture_ref=stderr_capture_ref,
            last_exit_class=exit_class,
            last_failure_id=failure_id,
        )


__all__ = ["ServiceCrashTransitionCoordinator"]
