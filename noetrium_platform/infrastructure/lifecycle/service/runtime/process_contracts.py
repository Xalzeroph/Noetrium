from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .capture_paths import ServiceCapturePaths
from .environment import MaterializedServiceEnvironment


class ProcessReconcileStatus(StrEnum):
    MISSING = "missing"
    EXACT = "exact"
    DRIFT = "drift"


@dataclass(frozen=True, slots=True)
class ProcessReconcileResult:
    status: ProcessReconcileStatus
    evidence_refs: tuple[str, ...]
    reason: str | None = None


class ServiceProcessDrift(RuntimeError):
    pass


class ExactProcessBackend(Protocol):
    """OS authority only; owns neither readiness nor environment selection."""

    def reconcile(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ProcessReconcileResult: ...

    def start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]: ...

    def alive(self, process: ServiceProcessIdentity) -> bool: ...

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]: ...


class ServiceReadinessProbe(Protocol):
    def wait_ready(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        backend: ExactProcessBackend,
    ) -> str: ...


__all__ = [
    "ExactProcessBackend",
    "ProcessReconcileResult",
    "ProcessReconcileStatus",
    "ServiceProcessDrift",
    "ServiceReadinessProbe",
]
