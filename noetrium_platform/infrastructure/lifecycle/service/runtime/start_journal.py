from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from dataclasses import replace
import hashlib
import time

from .prepared_start import ServiceStartRecoveryHandle
from .start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase
from .start_intent_ports import ServiceStartIntentStorePort
from .start_intent_store import ServiceStartIntentConflict


def service_start_intent_id(contract: ServiceLaunchContract, attempt: int) -> str:
    raw = f"{contract.service_id}:{contract.digest()}:{attempt}".encode("utf-8")
    return "service-start:" + hashlib.sha256(raw).hexdigest()


class ServiceStartJournal:
    """Transition policy for durable service-start intents."""

    def __init__(self, store: ServiceStartIntentStorePort) -> None:
        self.store = store

    def prepare(
        self,
        contract: ServiceLaunchContract,
        *,
        attempt: int,
        recovery_handle: ServiceStartRecoveryHandle | None,
    ) -> ServiceStartIntent:
        intent_id = service_start_intent_id(contract, attempt)
        now = time.time()
        candidate = ServiceStartIntent(
            intent_id,
            contract.service_id,
            contract.digest(),
            attempt,
            ServiceStartIntentPhase.PREPARED,
            recovery_handle,
            None,
            now,
            now,
        )
        current = self.store.create_once(candidate)
        if (
            current.service_id != candidate.service_id
            or current.contract_digest != candidate.contract_digest
            or current.attempt != candidate.attempt
            or current.recovery_handle != candidate.recovery_handle
        ):
            raise ServiceStartIntentConflict("service-start intent identity already bound differently")
        return current

    def record_process(
        self,
        intent: ServiceStartIntent,
        process: ServiceProcessIdentity,
    ) -> ServiceStartIntent:
        current = self.store.get(intent.intent_id)
        if current.process is not None and current.process != process:
            raise ServiceStartIntentConflict("service-start intent process identity changed")
        if current.phase in {ServiceStartIntentPhase.STATE_COMMITTED, ServiceStartIntentPhase.COMPLETE}:
            if current.process != process:
                raise ServiceStartIntentConflict("committed service-start intent disagrees on process")
            return current
        updated = replace(
            current,
            phase=ServiceStartIntentPhase.PROCESS_CONFIRMED,
            process=process,
            updated_at=time.time(),
        )
        self.store.put(updated)
        return updated

    def state_committed(self, intent: ServiceStartIntent) -> ServiceStartIntent:
        current = self.store.get(intent.intent_id)
        if current.process is None:
            raise ServiceStartIntentConflict("cannot commit start state without process identity")
        if current.phase is ServiceStartIntentPhase.COMPLETE:
            return current
        updated = replace(current, phase=ServiceStartIntentPhase.STATE_COMMITTED, updated_at=time.time())
        self.store.put(updated)
        return updated

    def complete(self, intent: ServiceStartIntent) -> ServiceStartIntent:
        current = self.store.get(intent.intent_id)
        if current.process is None:
            raise ServiceStartIntentConflict("cannot complete service-start intent without process identity")
        updated = replace(current, phase=ServiceStartIntentPhase.COMPLETE, updated_at=time.time())
        self.store.put(updated)
        return updated

    def unresolved(self, contract: ServiceLaunchContract) -> ServiceStartIntent | None:
        items = self.store.unresolved(contract.service_id, contract.digest())
        if len(items) > 1:
            raise ServiceStartIntentConflict("multiple unresolved start intents for one frozen service contract")
        return items[0] if items else None


__all__ = ["ServiceStartJournal", "service_start_intent_id"]
