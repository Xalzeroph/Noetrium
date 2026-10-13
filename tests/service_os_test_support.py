from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.composition import build_service_supervisor
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_effect_journal import ServiceStartEffectJournal
from noetrium_platform.infrastructure.reliability.effect.runtime import sqlite_effect_intent_journal


def service_start_effects_for_state(state):
    from pathlib import Path
    state_path = Path(state.reference())
    return ServiceStartEffectJournal(
        sqlite_effect_intent_journal(
            state_path.with_name(state_path.name + ".start-effects.sqlite3")
        )
    )


def make_service_supervisor(state, adapter):
    """Test-only deterministic Effect-journal wiring."""
    return build_service_supervisor(
        state,
        service_start_effects_for_state(state),
        adapter,
    )


def ready_evidence(process, contract, ready_ref="ready", stdout_ref="stdout", stderr_ref="stderr", ready_at=1234.5):
    from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceReadyEvidence
    return ServiceReadyEvidence(contract.digest(), process, ready_ref, stdout_ref, stderr_ref, ready_at)
