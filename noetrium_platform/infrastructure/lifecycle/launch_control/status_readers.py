from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from .heartbeat_ports import ServiceHeartbeatReadPort
from .runtime_history_ports import RuntimeHistoryReadPort
from .runtime_state_ports import RuntimeControlStateReadPort
from .status_ports import RuntimeControlStatusObservation, ServiceHeartbeatObservation


class RuntimeControlStatusReader:
    """Read-only join over independently configured runtime state and history sources."""

    def __init__(self, state: RuntimeControlStateReadPort, history: RuntimeHistoryReadPort) -> None:
        self.state = state
        self.history = history

    def observe(self) -> RuntimeControlStatusObservation:
        if not self.state.exists():
            return RuntimeControlStatusObservation(None)
        state = self.state.read()
        errors = self.history.verify()
        tail_error = None
        if not errors:
            try:
                self.history.assert_tail_matches(state)
            except Exception as exc:
                tail_error = describe_exception(exc)
        refs = (self.state.reference(), self.history.reference(), *state.evidence_refs[-8:])
        return RuntimeControlStatusObservation(state, tuple(errors), tail_error, tuple(refs))


class ServiceHeartbeatStatusReader:
    """Read-only adapter hiding heartbeat file naming from status composition."""

    def __init__(self, store: ServiceHeartbeatReadPort) -> None:
        self.store = store

    def observe(self, deployment_id: str) -> ServiceHeartbeatObservation:
        if not self.store.exists(deployment_id):
            return ServiceHeartbeatObservation(None)
        return ServiceHeartbeatObservation(
            self.store.read(deployment_id),
            (f"heartbeat:{self.store.reference(deployment_id)}",),
        )


__all__ = ["RuntimeControlStatusReader", "ServiceHeartbeatStatusReader"]
