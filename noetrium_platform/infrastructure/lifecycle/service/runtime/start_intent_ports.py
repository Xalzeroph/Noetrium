from __future__ import annotations

from typing import Protocol

from .start_intent_contracts import ServiceStartIntent


class ServiceStartIntentReadPort(Protocol):
    def unresolved(self, service_id: str, contract_digest: str) -> tuple[ServiceStartIntent, ...]: ...


class ServiceStartIntentStorePort(ServiceStartIntentReadPort, Protocol):
    def get(self, intent_id: str) -> ServiceStartIntent: ...
    def create_once(self, intent: ServiceStartIntent) -> ServiceStartIntent: ...
    def put(self, intent: ServiceStartIntent) -> None: ...


__all__ = ["ServiceStartIntentReadPort", "ServiceStartIntentStorePort"]
