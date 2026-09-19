from __future__ import annotations

from typing import Protocol

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationRecord

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionPort

from .contracts import (
    ServerDiagnosticReport,
    ServerHealthReport,
    ServerRuntimeHealthSpec,
    ServerSessionDiagnostic,
)


class ServerHealthProbePort(Protocol):
    """Derive health facts from an injected server connection."""

    def probe(
        self,
        connection: ServerConnectionPort,
        *,
        interactive: bool = False,
        specification: ServerRuntimeHealthSpec | None = None,
    ) -> ServerHealthReport: ...


class ServerDiagnosticProjectorPort(Protocol):
    """Join observed facts without owning a command or server registry."""

    def project(
        self,
        *,
        server_id: str,
        profile_digest: str,
        operation_log: str,
        health: ServerHealthReport,
        pending_operations: tuple[ServerOperationRecord, ...],
        recent_operations: tuple[ServerOperationRecord, ...],
        session: ServerSessionDiagnostic | None = None,
    ) -> ServerDiagnosticReport: ...


__all__ = ["ServerDiagnosticProjectorPort", "ServerHealthProbePort"]
