from __future__ import annotations

from typing import Protocol

from .contracts import (
    PersistentSessionObservation,
    PersistentSessionReport,
    PersistentSessionSnapshot,
    PersistentSessionSpec,
)
from .controller import PersistentSessionLaunchManifestPort, RuntimeControllerCommand


class PersistentSessionControlPort(Protocol):
    """Backend transport port; tmux/systemd/etc. implement this boundary."""

    @property
    def backend_id(self) -> str: ...

    @property
    def identity_digest(self) -> str: ...

    @property
    def identity_verified(self) -> bool: ...

    def inspect(self, session_name: str) -> PersistentSessionSnapshot: ...

    def verify_snapshot(
        self,
        spec: PersistentSessionSpec,
        snapshot: PersistentSessionSnapshot,
    ) -> tuple[str, ...]: ...

    def create_detached(self, spec: PersistentSessionSpec) -> PersistentSessionSnapshot: ...

    def terminate(self, session_name: str) -> tuple[str, ...]: ...

    def attach_argv(self, session_name: str) -> tuple[str, ...]: ...


class PersistentSessionRuntimePort(Protocol):
    """Durable binding + transport reconciliation exposed to runtime orchestration."""

    @property
    def backend_id(self) -> str: ...

    @property
    def transport_identity_digest(self) -> str: ...

    @property
    def transport_identity_verified(self) -> bool: ...

    def ensure(self, spec: PersistentSessionSpec) -> PersistentSessionReport: ...

    def inspect(self, spec: PersistentSessionSpec) -> PersistentSessionSnapshot: ...

    def terminate(self, spec: PersistentSessionSpec) -> tuple[str, ...]: ...


class PersistentSessionStatusProbePort(Protocol):
    def observe(self) -> PersistentSessionObservation: ...


class PersistentSessionHostPort(Protocol):
    @property
    def transport_backend_id(self) -> str: ...

    @property
    def transport_identity_digest(self) -> str: ...

    @property
    def transport_identity_verified(self) -> bool: ...

    def spec(
        self,
        manifest: PersistentSessionLaunchManifestPort,
        *,
        control_id: str,
        command: RuntimeControllerCommand,
    ) -> PersistentSessionSpec: ...


__all__ = [
    "PersistentSessionControlPort",
    "PersistentSessionRuntimePort",
    "PersistentSessionStatusProbePort",
    "PersistentSessionHostPort",
]
