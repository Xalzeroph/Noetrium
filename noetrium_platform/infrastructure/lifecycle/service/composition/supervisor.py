from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_ports import ServiceStartIntentStorePort
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_journal import ServiceStartJournal
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_ports import ServiceStateStorePort
from noetrium_platform.infrastructure.lifecycle.service.runtime.supervision_contracts import ServiceProcessAdapter
from noetrium_platform.infrastructure.lifecycle.service.runtime.supervisor import ExactServiceSupervisor


def build_service_supervisor(
    state: ServiceStateStorePort,
    intents: ServiceStartIntentStorePort,
    adapter: ServiceProcessAdapter,
) -> ExactServiceSupervisor:
    """Compose one exact service supervisor from explicit state, intent and process seams."""

    return ExactServiceSupervisor(
        state,
        adapter,
        start_journal=ServiceStartJournal(intents),
    )


__all__ = ["build_service_supervisor"]
