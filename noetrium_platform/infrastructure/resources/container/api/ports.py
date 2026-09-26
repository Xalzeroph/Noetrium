from __future__ import annotations

from typing import Protocol

from .contracts import (
    DockerContainerObservation,
    ManagedDockerContainerLease,
)


class DockerCommandResultPort(Protocol):
    returncode: int
    stdout: str
    stderr: str


class DockerCommandRunnerPort(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> DockerCommandResultPort: ...


class DockerManagedContainerPort(Protocol):
    @property
    def docker_executable(self) -> str: ...
    def assert_expansion_admissible(self) -> None: ...
    def inspect(self, reference: str) -> DockerContainerObservation | None: ...
    def list_managed(self) -> tuple[DockerContainerObservation, ...]: ...
    def wait_running(
        self,
        reference: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> DockerContainerObservation: ...
    def remove(self, reference: str, *, force: bool = True) -> None: ...


class DockerReconcileStopPort(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


class DockerContainerLeaseGuardPort(Protocol):
    @property
    def handles(self) -> tuple[ManagedDockerContainerLease, ...]: ...
    def start(self) -> None: ...
    def assert_healthy(self) -> None: ...
    def close(self) -> None: ...


class DockerContainerLeaseGuardFactoryPort(Protocol):
    def create(
        self,
        handles: tuple[ManagedDockerContainerLease, ...],
    ) -> DockerContainerLeaseGuardPort: ...


__all__ = [
    "DockerCommandRunnerPort",
    "DockerContainerLeaseGuardFactoryPort",
    "DockerContainerLeaseGuardPort",
    "DockerManagedContainerPort",
    "DockerReconcileStopPort",
]
