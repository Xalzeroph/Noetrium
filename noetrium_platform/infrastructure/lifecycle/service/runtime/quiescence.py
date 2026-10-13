from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from dataclasses import dataclass
from typing import Protocol

from .contracts import ServicePhase
from .process_contracts import ServiceProcessDrift
from .service_state_contracts import ServiceSupervisorState
from .start_intent_contracts import ServiceStartIntent


@dataclass(frozen=True, slots=True)
class ServiceQuiescenceObservation:
    service_id: str
    quiescent: bool
    summary: str
    evidence_refs: tuple[str, ...] = ()


class ServiceRuntimeInspectionPort(Protocol):
    def observe_state(self, contract: ServiceLaunchContract) -> ServiceSupervisorState | None: ...
    def reconcile_exact(self, contract: ServiceLaunchContract): ...
    def unresolved_start(self, contract: ServiceLaunchContract) -> ServiceStartIntent | None: ...


class ExactServiceQuiescenceProbe:
    """Read-only proof that one exact service contract has no live/uncertain process effect."""

    _SAFE_PHASES = frozenset({ServicePhase.NEW, ServicePhase.EXITED})

    def __init__(
        self,
        runtime: ServiceRuntimeInspectionPort,
        contract: ServiceLaunchContract,
    ) -> None:
        self.runtime = runtime
        self.contract = contract

    def observe(self) -> ServiceQuiescenceObservation:
        refs: list[str] = [f"service-contract:{self.contract.digest()}"]
        unresolved = self.runtime.unresolved_start(self.contract)
        if unresolved is not None:
            refs.append(
                f"service-start-effect:{unresolved.intent_id}:{unresolved.phase.value}"
            )
            return ServiceQuiescenceObservation(
                self.contract.service_id,
                False,
                "unresolved service-start effect prevents release retirement",
                tuple(refs),
            )

        state = self.runtime.observe_state(self.contract)
        if state is not None:
            refs.append(
                f"service-state:{state.phase.value}:{state.contract_digest}"
            )

        # Projection absence or an EXITED projection is never evidence of
        # physical absence.  Always reconcile exact process identities retained
        # by causal Effect truth against the physical backend.
        try:
            reconciled = self.runtime.reconcile_exact(self.contract)
        except ServiceProcessDrift as exc:
            refs.append(f"service-process-drift:{type(exc).__name__}")
            return ServiceQuiescenceObservation(
                self.contract.service_id,
                False,
                "physical service generation drift prevents release retirement",
                tuple(refs),
            )
        refs.extend(reconciled.evidence_refs)
        if reconciled.process is not None:
            process = reconciled.process
            refs.append(
                "service-process:"
                f"{process.pid}:{process.start_identity}:"
                f"anchor={process.anchor_pid}:{process.anchor_start_identity}"
            )
            return ServiceQuiescenceObservation(
                self.contract.service_id,
                False,
                "exact service process or owned fork tree is still live",
                tuple(dict.fromkeys(refs)),
            )

        if state is None:
            return ServiceQuiescenceObservation(
                self.contract.service_id,
                True,
                "no live process remains for any effect-confirmed service generation",
                tuple(dict.fromkeys(refs)),
            )
        if state.phase not in self._SAFE_PHASES:
            return ServiceQuiescenceObservation(
                self.contract.service_id,
                False,
                f"service supervisor phase {state.phase.value} is not a quiescent terminal phase",
                tuple(dict.fromkeys(refs)),
            )
        return ServiceQuiescenceObservation(
            self.contract.service_id,
            True,
            f"service is physically absent and quiescent in phase {state.phase.value}",
            tuple(dict.fromkeys(refs)),
        )



__all__ = ["ExactServiceQuiescenceProbe", "ServiceQuiescenceObservation", "ServiceRuntimeInspectionPort"]
