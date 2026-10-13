from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.runtime.start_effect_journal import (
    ServiceStartEffectJournal,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_ports import (
    ServiceStateStorePort,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.supervision_contracts import (
    ServiceProcessAdapter,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.supervisor import (
    ExactServiceSupervisor,
)


def build_service_supervisor(
    state: ServiceStateStorePort,
    start_effects: ServiceStartEffectJournal,
    adapter: ServiceProcessAdapter,
) -> ExactServiceSupervisor:
    return ExactServiceSupervisor(
        state,
        adapter,
        start_effects=start_effects,
    )


__all__ = ["build_service_supervisor"]
