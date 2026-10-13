from __future__ import annotations

from typing import Protocol

from .state import ModelRunState


class ModelSupervisorStateStorePort(Protocol):
    def write(self, state: ModelRunState) -> None: ...


__all__ = ["ModelSupervisorStateStorePort"]
