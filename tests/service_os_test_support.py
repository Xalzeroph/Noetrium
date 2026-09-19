from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.composition import build_service_supervisor
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore


def make_service_supervisor(state, adapter):
    """Test-only deterministic directory wiring; production code must inject both stores explicitly."""
    from pathlib import Path
    state_path = Path(state.reference())
    intent_root = state_path.with_name(state_path.name + ".start-intents")
    return build_service_supervisor(state, DirectoryServiceStartIntentStore(intent_root), adapter)


def ready_evidence(process, contract, ready_ref="ready", stdout_ref="stdout", stderr_ref="stderr", ready_at=1234.5):
    from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceReadyEvidence
    return ServiceReadyEvidence(contract.digest(), process, ready_ref, stdout_ref, stderr_ref, ready_at)
