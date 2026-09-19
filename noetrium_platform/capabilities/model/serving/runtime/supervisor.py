from __future__ import annotations

from ..api.state import ModelPhase, ModelRunState
from ..api.supervisor_ports import ModelSupervisorStateStorePort


class ModelSupervisor:
    """Owns model-service phase transitions; storage is injected through a narrow port."""

    def __init__(self, state_store: ModelSupervisorStateStorePort, initial: ModelRunState) -> None:
        self.state_store = state_store
        self.state = initial
        self.state_store.write(initial)

    def transition(self, phase: ModelPhase, **changes: object) -> ModelRunState:
        self.state = self.state.transition(phase, **changes)
        self.state_store.write(self.state)
        return self.state


__all__ = ["ModelSupervisor"]
