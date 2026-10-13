from __future__ import annotations

from typing import Protocol

from .contracts import GateReport, GateRequest


class GatePort(Protocol):
    @property
    def gate_id(self) -> str: ...

    def evaluate(self, request: GateRequest) -> GateReport: ...


class GateCompositionPort(Protocol):
    def compose(self, gate_id: str, children: tuple[GatePort, ...]) -> GatePort: ...


__all__ = ["GateCompositionPort", "GatePort"]
