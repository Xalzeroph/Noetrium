from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    freeze_json,
)

from .contracts import EmbodiedActionCommand, EpisodeSpec


@dataclass(frozen=True, slots=True)
class SimulatorObservation:
    """Provider-neutral simulator observation returned by downstream backends."""

    raw_payload: bytes
    normalized_payload: JsonObject
    status: str = "ok"
    reward: float | None = None
    success: bool = False
    terminated: bool = False
    truncated: bool = False
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.raw_payload) is not bytes:
            raise TypeError("simulator observation raw_payload must be bytes")
        if not isinstance(self.normalized_payload, Mapping):
            raise TypeError("simulator observation normalized_payload must be an object")
        if type(self.status) is not str or not self.status.strip():
            raise ValueError("simulator observation status is required")
        if self.reward is not None and (
            isinstance(self.reward, bool)
            or not isinstance(self.reward, (int, float))
        ):
            raise TypeError("simulator observation reward must be numeric or None")
        if type(self.success) is not bool:
            raise TypeError("simulator observation success must be boolean")
        if type(self.terminated) is not bool or type(self.truncated) is not bool:
            raise TypeError("simulator observation terminal flags must be boolean")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("simulator observation metadata must be an object")
        object.__setattr__(
            self,
            "normalized_payload",
            freeze_json(self.normalized_payload),
        )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class SimulatorStep:
    """One exact simulator action application plus resulting observation."""

    observation: SimulatorObservation
    action_status: str = "applied"
    action_receipt: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation, SimulatorObservation):
            raise TypeError("simulator step requires SimulatorObservation")
        if type(self.action_status) is not str or not self.action_status.strip():
            raise ValueError("simulator action_status is required")
        object.__setattr__(self, "action_receipt", freeze_json(self.action_receipt))


@runtime_checkable
class EmbodiedSimulatorBackendPort(Protocol):
    """Downstream simulator extension seam consumed by generic environment mechanics."""

    @property
    def identity_digest(self) -> str: ...

    def reset(
        self,
        episode: EpisodeSpec,
        context: ExecutionContext,
    ) -> SimulatorObservation: ...

    def step(
        self,
        command: EmbodiedActionCommand,
        context: ExecutionContext,
    ) -> SimulatorStep: ...

    def close(self) -> None: ...


__all__ = [
    "EmbodiedSimulatorBackendPort",
    "SimulatorObservation",
    "SimulatorStep",
]
