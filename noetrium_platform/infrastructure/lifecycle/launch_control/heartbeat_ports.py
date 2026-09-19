from __future__ import annotations

from typing import Protocol

from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat


class ServiceHeartbeatReadPort(Protocol):
    def exists(self, deployment_id: str) -> bool: ...

    def read(self, deployment_id: str) -> ServiceHeartbeat: ...

    def reference(self, deployment_id: str) -> str: ...


class ServiceHeartbeatStorePort(ServiceHeartbeatReadPort, Protocol):
    def write(self, heartbeat: ServiceHeartbeat) -> None: ...


__all__ = ["ServiceHeartbeatReadPort", "ServiceHeartbeatStorePort"]
